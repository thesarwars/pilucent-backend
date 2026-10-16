"""Gated operations (doc §6): a reason, an effective date, and an audit entry.

A refusal still states what the change would have done (§9): a classification
change says how many completed payroll runs it touches and whether it is
retroactive; a separation says what the employee would be owed.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from common import clock
from rulebookio.book import rule_book

from ..choices import ClassificationChoices, SeparationTypeChoices, TrackedFieldChoices
from ..models import Employee, EmployeeFieldHistory
from .salary import structure_in_force
from .statutory import retirement_age_warning, separation_entitlement
from .validation import validate_reason


class GatedRefused(Exception):
    def __init__(self, errors, consequence=None, status=400):
        self.errors = errors
        self.consequence = consequence
        self.status = status
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _actor(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def _reason(text, consequence):
    try:
        return validate_reason(text)
    except ValidationError as exc:
        raise GatedRefused({"reason": exc.messages}, consequence) from None


def _locked(employee):
    return Employee.objects.select_for_update().get(pk=employee.pk)


# ------------------------------------------------------- classification §6.1


def change_classification(employee, *, to, effective, reason, user=None):
    """WORKER ↔ NON_WORKER. Determined by the work performed, not the job
    title (s.2(65), designation-blind since the 2026 amendment).

    The classification is a single column, not an effective-dated record, so
    a change dated in the future would apply now -- and drop this year's
    projected festival bonuses months early. It is refused until its date.
    """
    if to not in ClassificationChoices.values:
        raise GatedRefused({"to": [f"to must be one of {', '.join(ClassificationChoices.values)}."]})
    if effective is None:
        raise GatedRefused({"effective": ["An effective date is required."]})
    consequence = {
        "completedPayrollRuns": employee.completed_payroll_runs,
        "retroactive": effective < clock.today(),
    }
    if to == employee.classification:
        raise GatedRefused({"to": [f"The employee is already classified {to}."]}, consequence)
    if effective > clock.today():
        raise GatedRefused({"effective": [
            f"A classification change applies when it is recorded: record it on or after "
            f"{effective.isoformat()}."]}, consequence)
    if employee.doj and effective < employee.doj:
        raise GatedRefused({"effective": [
            f"The change cannot take effect before the date of joining ({employee.doj.isoformat()})."]}, consequence)
    reason = _reason(reason, consequence)
    labels = dict(ClassificationChoices.choices)
    with transaction.atomic():
        locked = _locked(employee)
        before = locked.classification
        if before == to:  # the same change, made meanwhile
            raise GatedRefused({"to": [f"The employee is already classified {to}."]}, consequence, status=409)
        locked.classification = to
        locked.save(update_fields=["classification", "updated_at"])
        entry = EmployeeFieldHistory.objects.create(
            employee=locked, field=TrackedFieldChoices.CLASSIFICATION, date=effective,
            from_value=labels.get(before, before or ""), to_value=labels[to],
            by=user, by_name=_actor(user), reason=reason,
        )
    employee.classification = to
    return {"classification": to, "effective": effective.isoformat(), **consequence, "history": entry}


# ----------------------------------------------------------- separation §6.3


def separation_preview(employee, separation_type, on, gross_misconduct=False):
    """What the employee would be owed. Needs a salary structure (the wage)
    and a date of joining (the service)."""
    structure = structure_in_force(employee, on)
    block = maternity_block(employee, on)
    protection = [{"key": "maternity", "message": block["message"], "citation": block["citation"]}] if block else []
    if structure is None or employee.doj is None:
        return {"available": False, "warnings": protection, "message": (
            "No salary structure in force on the separation date." if structure is None
            else "No date of joining on file: length of service cannot be computed.")}
    book = rule_book(on)
    out = separation_entitlement(employee, structure, separation_type, on, book, gross_misconduct)
    warnings = list(protection)
    if separation_type == SeparationTypeChoices.RETIREMENT:
        warning = retirement_age_warning(employee, on, book)
        if warning:
            warnings.append(warning)
    return {"available": True, **out, "warnings": warnings}


def maternity_block(employee, on):
    """s.50 maternity protection, from the leave module (None when clear)."""
    from leaveledgerio.services.maternity import separation_block

    return separation_block(employee, on) if on else None


def separate(employee, *, separation_type, on, reason, gross_misconduct=False, user=None, maternity_override=False):
    """Records `separatedOn` and `separationType`. Until the final settlement
    runs the employee is a hard block on payroll (§3.1). Inside maternity
    protection (s.50) it is refused unless overridden, with the reason on
    the record."""
    if separation_type not in SeparationTypeChoices.values:
        raise GatedRefused({"type": [f"type must be one of {', '.join(SeparationTypeChoices.values)}."]})
    if on is None:
        raise GatedRefused({"date": ["A separation date is required."]})
    if employee.separated_on:
        raise GatedRefused({"separation": [
            f"Already separated on {employee.separated_on.isoformat()} ({employee.separation_type.lower()})."]},
            status=409)
    if employee.doj and on < employee.doj:
        raise GatedRefused({"date": [
            f"Separation cannot precede the date of joining ({employee.doj.isoformat()})."]})
    if gross_misconduct and separation_type != SeparationTypeChoices.DISMISSAL:
        raise GatedRefused({"gross_misconduct": ["Gross misconduct applies to a dismissal only."]})
    entitlement = separation_preview(employee, separation_type, on, gross_misconduct)
    block = maternity_block(employee, on)
    if block and not maternity_override:
        raise GatedRefused({"separation": [block["message"]]}, {"entitlement": entitlement, "maternity": block},
                           status=409)
    reason = _reason(reason, {"entitlement": entitlement})
    if block:
        reason = f"Maternity protection ({block['case']}, {block['citation']}) overridden: {reason}"
    label = dict(SeparationTypeChoices.choices)[separation_type]
    with transaction.atomic():
        locked = _locked(employee)
        if locked.separated_on:
            raise GatedRefused({"separation": ["Separated meanwhile. Reload the profile."]}, status=409)
        locked.separated_on, locked.separation_type = on, separation_type
        locked.save(update_fields=["separated_on", "separation_type", "updated_at"])
        entry = EmployeeFieldHistory.objects.create(
            employee=locked, field=TrackedFieldChoices.SEPARATION, date=on,
            from_value="In service", to_value=label, by=user, by_name=_actor(user), reason=reason,
        )
    employee.separated_on, employee.separation_type = on, separation_type
    return {"separatedOn": on.isoformat(), "separationType": separation_type,
            "settlementOutstanding": True, "entitlement": entitlement, "history": entry}
