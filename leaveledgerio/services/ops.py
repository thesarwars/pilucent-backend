"""Leave writes (backend spec §7): requests and their holds, grants and
corrections, the accrual run, the year-end close, encashment, and maternity.

Every write validates against `spendable()` -- never the raw ledger -- and
goes to the audit. Nothing that writes more than one row commits without a
preview first.
"""

from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from common import clock
from common.money import round_to_paisa
from employeeio.models import Employee
from employeeio.services.validation import validate_reason

from ..choices import (
    CycleKindChoices as CK,
    EncashmentStatusChoices as ES,
    LeaveAuditActionChoices as A,
    LedgerReasonChoices as R,
    RequestStatusChoices as S,
)
from ..choices import LeaveEventChoices as E
from ..models import Encashment, LeaveCycle, LeaveHold, LeaveRequest, LedgerEntry
from .events import emit
from .core import (
    ZERO,
    Book,
    LeaveRefused,
    actor_name,
    audit,
    cycle_bounds,
    cycle_for,
    d4,
    day_breakdown,
    days_str,
    ensure_types,
    fmt,
    months_between,
    plural,
    position,
    position_sentence,
    post,
    restriction,
    type_of,
)


def _reason(text, what="a reason"):
    try:
        return validate_reason(text)
    except ValidationError as exc:
        raise LeaveRefused({"reason": [f"Give {what}. {' '.join(exc.messages)}"]}) from None


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _next_reference(model, company, prefix, year):
    """LR-2026-000123: the next number for the year, per company."""
    head = f"{prefix}-{year}-"
    last = (model.objects.filter(company=company, reference__startswith=head).order_by("-reference")
            .values_list("reference", flat=True).first())
    n = int(last[len(head):]) + 1 if last else 1
    return f"{head}{n:06d}"


def _create_with_reference(model, company, prefix, year, **fields):
    for _ in range(5):
        try:
            with transaction.atomic():
                return model.objects.create(company=company, reference=_next_reference(model, company, prefix, year),
                                            **fields)
        except IntegrityError as exc:
            if "reference" not in str(exc):
                raise
    raise LeaveRefused({"reference": ["Could not allocate a reference; try again."]}, status=409)


def _lock(employee):
    """Serialise writes for one employee: two submissions in the same second
    must not each see the other's days as free."""
    return Employee.objects.select_for_update().get(pk=employee.pk)


def _date(value, field):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise LeaveRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


# =================================================================== requests


def _request_cycle(employee, ltype, from_date, to_date, book):
    if ltype.cycle_kind == CK.ROLLING:
        # The credit that lapses soonest and is still open on the first day.
        cycle = (LeaveCycle.objects.filter(employee=employee, leave_type=ltype, starts_on__lte=from_date,
                                           ends_on__gte=from_date).order_by("ends_on").first())
        if cycle is None:
            raise LeaveRefused({"leaveType": [
                f"No {ltype.name.lower()} credit is open on {fmt(from_date)}: a credit comes from working a "
                "holiday, and lapses after its window."]})
        latest = (LeaveCycle.objects.filter(employee=employee, leave_type=ltype, ends_on__gte=from_date)
                  .order_by("-ends_on").values_list("ends_on", flat=True).first())
        if to_date > latest:
            raise LeaveRefused({"toDate": [f"The compensatory credit must be taken by {fmt(latest)}."]})
        return cycle
    first = cycle_bounds(ltype, employee, from_date)
    last = cycle_bounds(ltype, employee, to_date)
    if first is None:
        raise LeaveRefused({"fromDate": [f"{employee.name_en} has no {ltype.name.lower()} cycle on {fmt(from_date)}."]})
    if first != last:
        raise LeaveRefused({"toDate": [
            f"The leave crosses the end of the {ltype.name.lower()} year on {fmt(first[1])}. Split it into two "
            "requests, one each side."]})
    return cycle_for(employee, ltype, from_date, book)


def preview_request(company, employee, code, from_date, to_date, *, start_half="FULL", end_half="FULL",
                    exclude_request=None):
    """What the apply drawer shows before submitting: the breakdown, the
    position it will be tested against, and what would refuse it."""
    book = Book()
    ltype = type_of(company, code)
    from_date, to_date = _date(from_date, "fromDate"), _date(to_date, "toDate")
    if to_date < from_date:
        raise LeaveRefused({"toDate": ["The leave cannot end before it starts."]}, status=400)
    cycle = _request_cycle(employee, ltype, from_date, to_date, book)
    breakdown = day_breakdown(employee, ltype, from_date, to_date, start_half, end_half)
    as_of = max(clock.today(), cycle.starts_on) if cycle else clock.today()
    p = position(employee, ltype, as_of, cycle=cycle, exclude_request=exclude_request, book=book)
    return ltype, cycle, breakdown, p, book


def submit_request(company, employee, code, from_date, to_date, *, start_half="FULL", end_half="FULL", note="",
                   contact="", cover_code="", evidence="", is_advance=False, user=None):
    """§7.1. In order: restrictions, the day breakdown, consecutive limits,
    then availability against spendable(). On success the request reserves
    its days with a hold."""
    today = clock.today()
    from_date, to_date = _date(from_date, "fromDate"), _date(to_date, "toDate")
    ltype = type_of(company, code)
    if ltype.code == "MATERNITY":
        raise LeaveRefused({"leaveType": [
            "Maternity leave is granted by recording the notice (a maternity case), not by an application: it is "
            "statutory and cannot be declined."]})
    if employee.separated_on and from_date > employee.separated_on:
        raise LeaveRefused({"fromDate": [f"{employee.name_en} separated on {fmt(employee.separated_on)}."]})
    with transaction.atomic():
        _lock(employee)
        book = Book()
        rules = book.rules(from_date)
        why = restriction(employee, ltype, from_date, rules)
        if why:
            raise LeaveRefused({"leaveType": [why]})
        if from_date < today - timedelta(days=ltype.backdate_window_days):
            raise LeaveRefused({"fromDate": [
                f"{ltype.name} can be entered up to {ltype.backdate_window_days} days back; {fmt(from_date)} is "
                "earlier. Correct an older absence with a grant or debit, with a reason."]})
        _, cycle, breakdown, p, book = preview_request(company, employee, code, from_date, to_date,
                                                            start_half=start_half, end_half=end_half)
        days = d4(breakdown["consumed"])
        if days <= 0:
            raise LeaveRefused({"toDate": [f"{breakdown['sentence']} Nothing to take."]})
        if ltype.max_consecutive_days and days > ltype.max_consecutive_days:
            raise LeaveRefused({"toDate": [f"{ltype.name} is taken {ltype.max_consecutive_days} days at a time at most."]})
        if days < ltype.min_consecutive_days:
            raise LeaveRefused({"toDate": [f"{ltype.name} is taken {ltype.min_consecutive_days} days at a time at least."]})
        clash = (LeaveRequest.objects.filter(employee=employee, status__in=[S.SUBMITTED, S.APPROVED],
                                             from_date__lte=to_date, to_date__gte=from_date).first())
        if clash:
            raise LeaveRefused({"fromDate": [
                f"{employee.name_en} already has {clash.leave_type.name.lower()} on these dates ({clash.reference})."]})
        if is_advance and not ltype.advance_allowed:
            raise LeaveRefused({"isAdvance": [f"{ltype.name} is not granted in advance."]})
        if days > p.spendable and not ltype.allow_negative_balance and not is_advance:
            have = max(p.spendable, ZERO)
            hint = (f"Reduce it to {plural(have, 'day')}, or submit it as an advance request." if ltype.advance_allowed
                    else f"Reduce it to {plural(have, 'day')}." if have else "There is nothing left to take.")
            raise LeaveRefused({"days": [f"{employee.name_en} has {days_str(have)} {ltype.name.lower()} and asked "
                                         f"for {days_str(days)}. {hint}"]},
                               detail={"position": p.out(), "asked": days_str(days)})
        cover = None
        if cover_code:
            cover = Employee.objects.filter(company=company, code=cover_code).first()
            if cover is None:
                raise LeaveRefused({"coverCode": [f"No employee {cover_code}."]}, status=400)
        req = _create_with_reference(
            LeaveRequest, company, "LR", from_date.year, employee=employee, leave_type=ltype, cycle=cycle,
            from_date=from_date, to_date=to_date, start_half=start_half, end_half=end_half, days_consumed=days,
            day_breakdown=breakdown, note=(note or "").strip(), contact_during_leave=(contact or "").strip(),
            cover_employee=cover, evidence=(evidence or "").strip(), is_backdated=from_date < today,
            is_advance=bool(is_advance), created_by=_who(user), created_by_name=actor_name(user), on_behalf=True)
        LeaveHold.objects.create(company=company, request=req, employee=employee, leave_type=ltype, cycle=cycle,
                                 days=days)
        audit(company, req, A.REQUEST_SUBMITTED, user, on_behalf_of=employee,
              after={"type": ltype.code, "from": from_date.isoformat(), "to": to_date.isoformat(),
                     "days": days_str(days), "position": p.out()},
              rule_set=cycle.rule_set)
        emit(company, E.LEAVE_REQUESTED, employee=employee, entity_ref=req.reference, actor=user,
             payload={"type": ltype.code, "from": from_date.isoformat(), "to": to_date.isoformat(),
                      "days": days_str(days)},
             message=f"{req.reference}: {employee.name_en} asks {days_str(days)} days {ltype.name.lower()}")
    return req


def _get_request(company, reference, *, lock=False):
    qs = LeaveRequest.objects.filter(company=company, reference=reference).select_related("employee", "leave_type",
                                                                                          "cycle")
    if lock:
        qs = qs.select_for_update()
    req = qs.first()
    if req is None:
        raise LeaveRefused({"request": [f"No request {reference}."]}, status=404)
    return req


def _release(req):
    LeaveHold.objects.filter(request=req, released_at__isnull=True).update(released_at=timezone.now())


def approve_request(company, reference, *, user=None):
    """§7.2. Re-validated against the balance net of every OTHER live hold:
    the check that stops three approvers passing the same four days."""
    with transaction.atomic():
        req = _get_request(company, reference, lock=True)
        if req.status != S.SUBMITTED:
            raise LeaveRefused({"request": [f"{req.reference} is {req.get_status_display().lower()}, not waiting."]},
                               status=409)
        if user is not None and req.employee.user_id and req.employee.user_id == user.pk:
            raise LeaveRefused({"request": ["Nobody approves their own leave."]}, status=403)
        employee = _lock(req.employee)
        ltype = req.leave_type
        as_of = max(clock.today(), req.cycle.starts_on)
        p = position(employee, ltype, as_of, cycle=req.cycle if ltype.cycle_kind != CK.ROLLING else None,
                     exclude_request=req)
        if req.days_consumed > p.spendable and not ltype.allow_negative_balance and not req.is_advance:
            raise LeaveRefused({"request": [
                f"The balance moved since this was submitted: {position_sentence(p, ltype, 'free')}, and the request "
                f"needs {days_str(req.days_consumed)}. Decline it, or grant the days first."]},
                detail={"position": p.out()})
        entry = post(employee=employee, ltype=ltype, cycle=req.cycle, days=-req.days_consumed, reason=R.TAKEN,
                     effective=req.from_date, user=user,
                     basis=f"{ltype.name} {fmt(req.from_date)} – {fmt(req.to_date)}: "
                           f"{plural(req.days_consumed, 'day')} ({req.reference})",
                     source_ref=req.reference)
        _release(req)
        req.status = S.APPROVED
        req.decided_by = _who(user)
        req.decided_by_name = actor_name(user)
        req.decided_at = timezone.now()
        req.ledger_entry = entry
        req.save(update_fields=["status", "decided_by", "decided_by_name", "decided_at", "ledger_entry", "updated_at"])
        audit(company, req, A.REQUEST_APPROVED, user, on_behalf_of=employee,
              after={"entry": entry.reference, "days": days_str(req.days_consumed), "position": p.out()},
              rule_set=req.cycle.rule_set)
        emit(company, E.LEAVE_APPROVED, employee=employee, entity_ref=req.reference, actor=user,
             requester=req.created_by,
             payload={"type": ltype.code, "from": req.from_date.isoformat(), "to": req.to_date.isoformat(),
                      "days": days_str(req.days_consumed), "payRate": ltype.pay_rate, "entry": entry.reference},
             message=f"{req.reference} approved: {ltype.name.lower()} {fmt(req.from_date)}, "
                     f"{days_str(req.days_consumed)} days")
    return req


def decline_request(company, reference, *, reason="", user=None):
    reason = _reason(reason, "the reason for declining")
    with transaction.atomic():
        req = _get_request(company, reference, lock=True)
        if req.status != S.SUBMITTED:
            raise LeaveRefused({"request": [f"{req.reference} is {req.get_status_display().lower()}, not waiting."]},
                               status=409)
        if req.non_refusable:
            raise LeaveRefused({"request": ["A statutory entitlement is not declined."]}, status=409)
        _release(req)
        req.status = S.DECLINED
        req.decline_reason = reason
        req.decided_by = _who(user)
        req.decided_by_name = actor_name(user)
        req.decided_at = timezone.now()
        req.save(update_fields=["status", "decline_reason", "decided_by", "decided_by_name", "decided_at",
                                "updated_at"])
        audit(company, req, A.REQUEST_DECLINED, user, on_behalf_of=req.employee, reason=reason)
        emit(company, E.LEAVE_DECLINED, employee=req.employee, entity_ref=req.reference, actor=user,
             requester=req.created_by, payload={"reason": reason},
             message=f"{req.reference} declined: {reason}")
    return req


def withdraw_request(company, reference, *, reason="", user=None):
    with transaction.atomic():
        req = _get_request(company, reference, lock=True)
        if req.status != S.SUBMITTED:
            raise LeaveRefused({"request": [f"Only a waiting request is withdrawn; {req.reference} is "
                                            f"{req.get_status_display().lower()}."]}, status=409)
        _release(req)
        req.status = S.WITHDRAWN
        req.save(update_fields=["status", "updated_at"])
        audit(company, req, A.REQUEST_WITHDRAWN, user, on_behalf_of=req.employee, reason=(reason or "").strip())
    return req


def cancel_request(company, reference, *, reason="", user=None):
    """An approved absence that has not begun: the days go back with a
    CANCELLED entry beside the TAKEN one, never by editing it."""
    reason = _reason(reason, "the reason for cancelling")
    with transaction.atomic():
        req = _get_request(company, reference, lock=True)
        if req.status != S.APPROVED:
            raise LeaveRefused({"request": [f"Only approved leave is cancelled; {req.reference} is "
                                            f"{req.get_status_display().lower()}."]}, status=409)
        if req.non_refusable:
            raise LeaveRefused({"request": ["Maternity leave is changed through its case, not cancelled here."]},
                               status=409)
        if req.from_date <= clock.today():
            raise LeaveRefused({"request": [
                f"The absence began on {fmt(req.from_date)}. Correct what was taken with a grant, with a reason."]},
                status=409)
        entry = post(employee=req.employee, ltype=req.leave_type, cycle=req.cycle, days=req.days_consumed,
                     reason=R.CANCELLED, effective=req.from_date, user=user, source_ref=req.reference,
                     basis=f"{req.reference} cancelled before it began: {plural(req.days_consumed, 'day')} back — {reason}")
        req.status = S.CANCELLED
        req.save(update_fields=["status", "updated_at"])
        audit(company, req, A.REQUEST_CANCELLED, user, on_behalf_of=req.employee, reason=reason,
              after={"entry": entry.reference})
    return req


# ===================================================================== grants


def grant(company, employee, code, days, *, reason="", effective=None, user=None, book=None):
    """§7.3. A manual credit or debit is an ADJUSTMENT entry, not another
    kind of record: two sources of truth for a balance is what the ledger
    exists to prevent. A debit is tested against spendable()."""
    reason = _reason(reason, "the reason for the grant")
    days = d4(days)
    if days == 0:
        raise LeaveRefused({"days": ["A grant of nothing is not a grant."]}, status=400)
    ltype = type_of(company, code)
    effective = _date(effective, "effective") if effective else clock.today()
    book = book or Book()
    with transaction.atomic():
        _lock(employee)
        if ltype.cycle_kind == CK.ROLLING:
            rules = book.rules(effective)
            cycle = (LeaveCycle.objects.filter(employee=employee, leave_type=ltype, starts_on__lte=effective,
                                               ends_on__gte=effective).order_by("ends_on").first())
            if cycle is None:
                if days < 0:
                    raise LeaveRefused({"days": ["No compensatory credit is open to debit."]})
                cycle, _ = LeaveCycle.objects.get_or_create(
                    employee=employee, leave_type=ltype, starts_on=effective,
                    defaults={"company": company, "kind": CK.ROLLING, "rule_set": rules.rule_set,
                              "ends_on": effective + timedelta(days=rules.comp_due_days - 1)})
        elif ltype.cycle_kind == CK.EVENT:
            raise LeaveRefused({"leaveType": [f"{ltype.name} is granted by its event, not by hand."]})
        else:
            why = restriction(employee, ltype, effective, book.rules(effective), service=False)
            if why:
                raise LeaveRefused({"leaveType": [why]})
            cycle = cycle_for(employee, ltype, effective, book)
            if cycle is None:
                raise LeaveRefused({"effective": [f"{employee.name_en} has no {ltype.name.lower()} cycle on "
                                                  f"{fmt(effective)}."]})
        p = position(employee, ltype, max(effective, clock.today()), cycle=cycle if ltype.cycle_kind != CK.ROLLING
                     else None, book=book)
        if days < 0 and -days > p.spendable:
            raise LeaveRefused({"days": [f"{position_sentence(p, ltype, 'free to debit')}; a debit of "
                                         f"{days_str(-days)} would overdraw it."]}, detail={"position": p.out()})
        verb = "Granted" if days > 0 else "Debited"
        entry = post(employee=employee, ltype=ltype, cycle=cycle, days=days, reason=R.ADJUSTMENT, effective=effective,
                     user=user, on_behalf=True, basis=f"{verb} {plural(abs(days), 'day')} by hand: {reason}")
        audit(company, entry, A.GRANTED, user, on_behalf_of=employee, reason=reason,
              before={"position": p.out()}, after={"entry": entry.reference, "days": days_str(days)},
              rule_set=cycle.rule_set)
        emit(company, E.BALANCE_GRANTED, employee=employee, entity_ref=entry.reference, actor=user,
             payload={"type": ltype.code, "days": days_str(days), "reason": reason},
             message=f"{verb} {days_str(abs(days))} days {ltype.name.lower()}: {reason}")
    return entry


def bulk_grant(company, employees, code, days, *, reason="", effective=None, commit=False, user=None):
    """Preview first: the preview writes nothing and says which rows would be
    refused, and why."""
    reason_ok = None
    try:
        reason_ok = _reason(reason, "the reason for the grant")
    except LeaveRefused as exc:
        if commit:
            raise
        reason_ok = exc
    ltype = type_of(company, code)
    days = d4(days)
    effective = _date(effective, "effective") if effective else clock.today()
    book = Book()
    rows = []
    for e in employees:
        row = {"code": e.code, "nameEn": e.name_en, "days": days_str(days)}
        try:
            if not commit:
                with transaction.atomic():
                    sid = transaction.savepoint()
                    try:
                        grant(company, e, code, days, reason=reason if isinstance(reason_ok, str) else "x" * 10,
                              effective=effective, book=book)
                    finally:
                        transaction.savepoint_rollback(sid)
                row.update(outcome="OK")
            else:
                entry = grant(company, e, code, days, reason=reason, effective=effective, user=user, book=book)
                row.update(outcome="POSTED", entry=entry.reference)
        except LeaveRefused as exc:
            row.update(outcome="REFUSED", why=str(exc))
        rows.append(row)
    out = {"type": ltype.code, "commit": commit, "rows": rows,
           "ok": sum(1 for r in rows if r["outcome"] in ("OK", "POSTED")),
           "refused": sum(1 for r in rows if r["outcome"] == "REFUSED")}
    if isinstance(reason_ok, LeaveRefused):
        out["reasonError"] = str(reason_ok)
    return out


# ================================================================ accrual run


def days_worked_from_attendance(employee, start, end, book):
    """Days worked in [start, end] from attendance, under the payroll
    elections (the same count month close shows), and how much of the span
    attendance has settled. A day counts as settled when it has a status
    that is not an unresolved exception."""
    from employeeio.services.sites import site_of
    from timekeepingio.services.engine import Rules, days_worked_for_accrual
    from timekeepingio.services.ops import elections_of
    from timekeepingio.services.window import Window

    first = max(start, employee.doj or start)
    last = min(end, employee.separated_on or end)
    if last < first:
        return Decimal(0), 0, 0
    rules = Rules.from_rule_set(book.rule_set(last))
    w = Window(employee.company, site_of(employee), [employee], first, last, rules, strict_calendar=False,
               today=clock.today())
    recs = w.records(employee)
    settled = sum(1 for r in recs if r.status and r.status != "EXCEPTION" and r.day.year not in w.kinds.missing)
    flags = elections_of(employee.company, site_of(employee), last)["daysWorked"]
    if flags is None:
        from paysetio.services.resolve import ElectionUnanswered

        raise ElectionUnanswered("days_worked_basis")
    worked = Decimal(str(days_worked_for_accrual(recs, flags)))
    return worked, settled, len(recs)


def accrual_run(company, employees, as_of, *, days_worked=None, commit=False, user=None):
    """§5.3, §7.4. Earned leave for the last completed service year, posted
    into the next one (earned in arrears). Five outcomes per row: OK,
    CAPPED, NOT_ELIGIBLE, ALREADY_POSTED, REFUSED -- and NEEDS_DAYS where
    attendance does not cover the year and no figure was entered.

    Idempotent by construction: a second ACCRUAL for the same cycle is
    refused by the unique index, reported as ALREADY_POSTED."""
    as_of = _date(as_of, "asOf")
    days_worked = {str(k).upper(): v for k, v in (days_worked or {}).items() if v not in (None, "")}
    ltype = ensure_types(company)["EARNED"]
    book = Book()
    rows = []
    for e in employees:
        row = {"code": e.code, "nameEn": e.name_en, "establishment": e.establishment or None}
        rows.append(row)
        try:
            row.update(_accrue_one(company, e, ltype, as_of, days_worked.get(e.code), commit, user, book))
        except LeaveRefused as exc:
            row.update(outcome="REFUSED", why=str(exc))
    counts = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {"asOf": as_of.isoformat(), "commit": commit, "rows": rows, "counts": counts,
            "postable": sum(1 for r in rows if r["outcome"] in ("OK", "CAPPED"))}


def _accrue_one(company, e, ltype, as_of, entered, commit, user, book):
    rules = book.rules(as_of)
    why = restriction(e, ltype, as_of, rules, service=False)
    if why:
        return {"outcome": "NOT_ELIGIBLE", "why": why}
    if e.doj is None:
        return {"outcome": "REFUSED", "why": "No date of joining recorded: the service year cannot be placed."}
    current = cycle_bounds(ltype, e, as_of)
    if current is None:
        return {"outcome": "NOT_ELIGIBLE", "why": f"Joins on {fmt(e.doj)}."}
    start, end = cycle_bounds(ltype, e, current[0] - timedelta(days=1)) or (None, None)
    if start is None:
        return {"outcome": "NOT_ELIGIBLE",
                "why": f"In the first service year, to {fmt(current[1])}: earned leave is earned in arrears, "
                       f"after {rules.el_min_service_months} months ({ltype.statutory_basis})."}
    rules = book.rules(end)
    served = months_between(e.doj, end + timedelta(days=1))
    if served < rules.el_min_service_months:
        return {"outcome": "NOT_ELIGIBLE", "why": f"{served} months' service by {fmt(end)}; earned leave starts after "
                                                  f"{rules.el_min_service_months} ({ltype.statutory_basis})."}
    est = e.establishment
    if not est:
        return {"outcome": "REFUSED", "why": "No establishment recorded: the divisor and the cap depend on it."}
    adolescent = e.dob is not None and months_between(e.dob, end) < 18 * 12
    divisors = rules.el_divisor_adolescent if adolescent else rules.el_divisor
    if est not in divisors or est not in rules.el_cap:
        return {"outcome": "REFUSED", "why": f"No earned-leave divisor or cap for {est} in rule set {rules.version}."}
    divisor, cap = int(divisors[est]), d4(rules.el_cap[est])
    span = {"cycleFrom": start.isoformat(), "cycleTo": end.isoformat(), "divisor": divisor,
            "cap": days_str(cap), "adolescent": adolescent}

    if entered is not None:
        worked = d4(entered)
        if worked < 0 or worked > (end - start).days + 1:
            return {**span, "outcome": "REFUSED", "why": f"{entered} days worked does not fit a {(end - start).days + 1}-day year."}
        source = "entered"
    else:
        worked, settled, total = days_worked_from_attendance(e, start, end, book)
        if settled < total:
            return {**span, "outcome": "NEEDS_DAYS", "settled": settled, "total": total,
                    "why": f"Attendance has settled {settled} of {total} days of this service year. Enter the days "
                           "worked from the register."}
        source = "attendance"
    target = cycle_for(e, ltype, end + timedelta(days=1), book)
    if LedgerEntry.objects.filter(cycle=target, reason__in=[R.ACCRUAL, R.ACCRUAL_CAPPED],
                                  reversed_by__isnull=True).exists():
        return {**span, "outcome": "ALREADY_POSTED", "worked": days_str(worked), "source": source,
                "why": f"Already posted for the service year to {fmt(end)}."}
    raw = worked / divisor
    rounded = d4(raw.to_integral_value(rounding=ROUND_FLOOR))
    p = position(e, ltype, target.starts_on, cycle=target, book=book)
    room = cap - p.balance
    granted = ZERO if room <= 0 else min(rounded, room)
    capped = granted < rounded
    label = "an adolescent" if adolescent else est.replace("_", " ").lower()
    basis = (f"{days_str(worked)} days worked ÷ {divisor}, floored = {days_str(rounded)}; capped at {days_str(cap)} "
             f"for {'an' if label[0] in 'aeiou' else 'a'} {label}, so {days_str(granted)} granted "
             f"(service year {fmt(start)} – {fmt(end)}; {ltype.statutory_basis})")
    out = {**span, "worked": days_str(worked), "source": source, "raw": days_str(d4(raw)), "rounded": days_str(rounded),
           "balanceBefore": days_str(p.balance), "granted": days_str(granted), "capped": capped, "basis": basis,
           "outcome": "CAPPED" if capped else "OK"}
    if granted == 0 and not capped:
        out.update(outcome="NOT_ELIGIBLE", why=f"{days_str(worked)} days worked earns less than a day.")
        return out
    if commit:
        try:
            with transaction.atomic():
                entry = post(employee=e, ltype=ltype, cycle=target, days=granted,
                             reason=R.ACCRUAL if granted else R.ACCRUAL_CAPPED, effective=target.starts_on,
                             basis=basis, user=user, rule_set=rules.rule_set)
                audit(company, entry, A.ACCRUAL_POSTED, user, on_behalf_of=e, after=out, rule_set=rules.rule_set)
                emit(company, E.ACCRUAL_POSTED, employee=e, entity_ref=entry.reference, actor=user,
                     payload={"days": out["granted"], "capped": capped},
                     message=f"Earned leave: {out['granted']} days for the service year to {fmt(end)}")
            out["entry"] = entry.reference
        except IntegrityError:
            out.update(outcome="ALREADY_POSTED", why="Posted meanwhile by another run.")
    return out


# ============================================================== year-end close


def year_end_close(company, employees, as_of, *, commit=False, confirm=False, user=None):
    """§5.4. Dry run by default. For each earned-leave service year that
    ended before `as_of`: carry up to the cap into the next year as OPENING,
    forfeit the rest as FORFEITURE. Nothing posts until the caller confirms,
    because a close is reversed only entry by entry."""
    as_of = _date(as_of, "asOf")
    if commit and not confirm:
        raise LeaveRefused({"confirm": ["Confirm the close: it posts forfeitures that are reversed only one by one."]})
    ltype = ensure_types(company)["EARNED"]
    book = Book()
    rows = []
    cycles = (LeaveCycle.objects.filter(company=company, leave_type=ltype, employee__in=employees, ends_on__lt=as_of,
                                        closed_at__isnull=True).select_related("employee").order_by("ends_on"))
    for c in cycles:
        e = c.employee
        rules = book.rules(c.ends_on)
        row = {"code": e.code, "nameEn": e.name_en, "cycleFrom": c.starts_on.isoformat(), "cycleTo": c.ends_on.isoformat()}
        rows.append(row)
        est = e.establishment
        cap = d4(ltype.carry_forward_fixed_cap) if ltype.carry_forward_fixed_cap is not None else (
            d4(rules.el_cap[est]) if est in rules.el_cap else None)
        if cap is None:
            row.update(outcome="REFUSED", why="No establishment recorded: the cap depends on it.")
            continue
        p = position(e, ltype, c.ends_on, cycle=c, book=book)
        closing = p.spendable
        nxt = cycle_for(e, ltype, c.ends_on + timedelta(days=1), book, create=commit)
        already = position(e, ltype, nxt.starts_on, cycle=nxt, book=book).balance if nxt else ZERO
        room = max(cap - already, ZERO)
        carried = min(closing, room) if closing > 0 else closing
        forfeit = closing - carried if closing > 0 else ZERO
        row.update(closing=days_str(closing), cap=days_str(cap), alreadyInNext=days_str(already),
                   carried=days_str(carried), forfeited=days_str(forfeit), outcome="WILL_CLOSE")
        if p.held:
            row["warning"] = f"{days_str(p.held)} days held by undecided requests are not carried."
        if commit:
            with transaction.atomic():
                if forfeit > 0:
                    f = post(employee=e, ltype=ltype, cycle=c, days=-forfeit, reason=R.FORFEITURE, effective=c.ends_on,
                             user=user, basis=f"{plural(forfeit, 'day')} above the {days_str(cap)}-day cap "
                                              f"forfeited at the end of the service year ({ltype.statutory_basis})")
                    row["forfeitEntry"] = f.reference
                    emit(company, E.FORFEITED, employee=e, entity_ref=f.reference, actor=user,
                         payload={"days": days_str(forfeit), "cap": days_str(cap)},
                         message=f"{days_str(forfeit)} days of earned leave forfeited above the {days_str(cap)}-day cap")
                if carried:
                    o = post(employee=e, ltype=ltype, cycle=nxt, days=carried, reason=R.OPENING, effective=nxt.starts_on,
                             user=user, basis=f"Carried from the service year to {fmt(c.ends_on)}: "
                                              f"{plural(carried, 'day')}" + (f", the cap of {days_str(cap)} applied"
                                                                             if forfeit else ""))
                    row["openingEntry"] = o.reference
                c.closed_at = timezone.now()
                c.closed_by = _who(user)
                c.save(update_fields=["closed_at", "closed_by", "updated_at"])
                audit(company, c, A.YEAR_CLOSED, user, on_behalf_of=e, after=row, rule_set=rules.rule_set)
            row["outcome"] = "CLOSED"
    return {"asOf": as_of.isoformat(), "commit": commit, "rows": rows,
            "forfeited": days_str(sum((d4(r.get("forfeited") or 0) for r in rows), ZERO)),
            "carried": days_str(sum((d4(r.get("carried") or 0) for r in rows), ZERO))}


# ================================================================= encashment


def _encash_limits(employee, ltype, cycle, rules, book):
    p = position(employee, ltype, max(clock.today(), cycle.starts_on), cycle=cycle, book=book)
    ceiling = d4((max(p.spendable, ZERO) * rules.encash_fraction).to_integral_value(rounding=ROUND_FLOOR))
    return p, ceiling


def request_encashment(company, employee, days, *, user=None):
    """§7.6 step one. At most the statutory fraction of the SPENDABLE balance
    -- half of what can be spent is not half of the ledger -- once a cycle."""
    from employeeio.services.salary import structure_in_force

    days = d4(days)
    if days <= 0:
        raise LeaveRefused({"days": ["Encash a positive number of days."]}, status=400)
    ltype = ensure_types(company)["EARNED"]
    book = Book()
    today = clock.today()
    with transaction.atomic():
        _lock(employee)
        rules = book.rules(today)
        why = restriction(employee, ltype, today, rules, service=False)
        if why:
            raise LeaveRefused({"employee": [why]})
        cycle = cycle_for(employee, ltype, today, book)
        if cycle is None:
            raise LeaveRefused({"employee": [f"{employee.name_en} has no earned-leave year open."]})
        if Encashment.objects.filter(employee=employee, leave_type=ltype, cycle=cycle).exclude(status=ES.DECLINED).exists():
            raise LeaveRefused({"days": [f"Earned leave is encashed {rules.encash_per_cycle} time a service year, and "
                                         f"this year's is already on file."]}, status=409)
        p, ceiling = _encash_limits(employee, ltype, cycle, rules, book)
        if days > ceiling:
            raise LeaveRefused({"days": [
                f"{position_sentence(p, ltype, 'free to encash')}; at most {days_str(ceiling)} encashable "
                f"({days_str(rules.encash_fraction * 100)}% of what can be spent, {rules.citations['encashmentFraction']})."]},
                detail={"position": p.out(), "ceiling": days_str(ceiling)})
        structure = structure_in_force(employee, today)
        if structure is None:
            raise LeaveRefused({"employee": [f"{employee.name_en} has no salary structure in force: there is no wage "
                                             "to encash at."]})
        gross = structure.gross
        divisor = rules.day_wage_divisor
        rate = d4(gross / divisor)
        enc = _create_with_reference(
            Encashment, company, "EN", today.year, employee=employee, leave_type=ltype, cycle=cycle, days=days,
            wage_base=d4(gross), divisor=divisor, daily_rate=rate, amount=d4(round_to_paisa(rate * days)),
            rate_basis=f"Gross ÷ {divisor} — the encashment divisor ({rules.citations['dayWageDivisor']})",
            requested_by=_who(user), requested_by_name=actor_name(user), rule_set=rules.rule_set)
        audit(company, enc, A.ENCASHMENT_REQUESTED, user, on_behalf_of=employee,
              after={"days": days_str(days), "ceiling": days_str(ceiling), "position": p.out()},
              rule_set=rules.rule_set)
    return enc


def _get_encashment(company, reference):
    enc = (Encashment.objects.select_for_update().filter(company=company, reference=reference)
           .select_related("employee", "leave_type", "cycle").first())
    if enc is None:
        raise LeaveRefused({"encashment": [f"No encashment {reference}."]}, status=404)
    return enc


def approve_encashment(company, reference, *, user=None):
    """The approval is what removes the days: the ENCASHED entry is written
    here, after re-testing against what can be spent now."""
    with transaction.atomic():
        enc = _get_encashment(company, reference)
        if enc.status != ES.SUBMITTED:
            raise LeaveRefused({"encashment": [f"{enc.reference} is {enc.get_status_display().lower()}."]}, status=409)
        if user is not None and enc.employee.user_id and enc.employee.user_id == user.pk:
            raise LeaveRefused({"encashment": ["Nobody approves their own encashment."]}, status=403)
        _lock(enc.employee)
        book = Book()
        rules = book.rules(clock.today())
        p, ceiling = _encash_limits(enc.employee, enc.leave_type, enc.cycle, rules, book)
        if enc.days > ceiling:
            raise LeaveRefused({"encashment": [
                f"The balance moved: {position_sentence(p, enc.leave_type, 'free to encash')}; at most "
                f"{days_str(ceiling)} encashable now, and this asks {days_str(enc.days)}. Decline it."]},
                detail={"position": p.out()})
        entry = post(employee=enc.employee, ltype=enc.leave_type, cycle=enc.cycle, days=-enc.days,
                     reason=R.ENCASHED, effective=clock.today(), user=user, source_ref=enc.reference,
                     basis=f"Encashed {plural(enc.days, 'day')} at {enc.rate_basis.split(' —')[0]} ({enc.reference})")
        enc.status = ES.APPROVED
        enc.approved_by = _who(user)
        enc.approved_by_name = actor_name(user)
        enc.approved_at = timezone.now()
        enc.ledger_entry = entry
        enc.save(update_fields=["status", "approved_by", "approved_by_name", "approved_at", "ledger_entry", "updated_at"])
        audit(company, enc, A.ENCASHMENT_APPROVED, user, on_behalf_of=enc.employee, after={"entry": entry.reference},
              rule_set=enc.rule_set)
        emit(company, E.ENCASHMENT_APPROVED, employee=enc.employee, entity_ref=enc.reference, actor=user,
             payload={"days": days_str(enc.days), "amount": str(enc.amount), "divisor": enc.divisor},
             message=f"{enc.reference} approved: {days_str(enc.days)} days of earned leave encashed")
    return enc


def decline_encashment(company, reference, *, reason="", user=None):
    reason = _reason(reason, "the reason for declining")
    with transaction.atomic():
        enc = _get_encashment(company, reference)
        if enc.status != ES.SUBMITTED:
            raise LeaveRefused({"encashment": [f"{enc.reference} is {enc.get_status_display().lower()}."]}, status=409)
        enc.status = ES.DECLINED
        enc.decline_reason = reason
        enc.save(update_fields=["status", "decline_reason", "updated_at"])
        audit(company, enc, A.ENCASHMENT_DECLINED, user, on_behalf_of=enc.employee, reason=reason)
    return enc


def mark_encashment_paid(company, reference, *, payment_month=None, user=None):
    """Stamps the payroll run and payslip reference, both derived from the
    record's own payment month."""
    with transaction.atomic():
        enc = _get_encashment(company, reference)
        if enc.status != ES.APPROVED:
            raise LeaveRefused({"encashment": [f"Only an approved encashment is paid; {enc.reference} is "
                                               f"{enc.get_status_display().lower()}."]}, status=409)
        if payment_month:
            try:
                y, m = (int(x) for x in str(payment_month).split("-")[:2])
                month = date(y, m, 1)
            except (TypeError, ValueError):
                raise LeaveRefused({"paymentMonth": ["paymentMonth is YYYY-MM."]}, status=400) from None
        else:
            month = clock.today().replace(day=1)
        enc.payment_month = month
        enc.payroll_ref = f"PAYRUN-{month:%Y-%m}"
        enc.payslip_ref = f"PS-{month:%Y-%m}-{enc.employee.code}"
        enc.status = ES.PAID
        enc.paid_at = timezone.now()
        enc.save(update_fields=["payment_month", "payroll_ref", "payslip_ref", "status", "paid_at", "updated_at"])
        audit(company, enc, A.ENCASHMENT_PAID, user, on_behalf_of=enc.employee,
              after={"payrollRef": enc.payroll_ref, "payslipRef": enc.payslip_ref})
    return enc


__all__ = [
    "accrual_run", "approve_encashment", "approve_request", "bulk_grant", "cancel_request", "decline_encashment",
    "decline_request", "grant", "mark_encashment_paid", "preview_request", "request_encashment", "submit_request",
    "withdraw_request", "year_end_close",
]
