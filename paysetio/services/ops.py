"""Payroll settings operations (§6): elect, propose and approve, the pay
schedule, the four schemes and their GL mapping, per-employee scheme
participation, readiness and the changelog.

Lifecycle of an effective-dated row (elections, schemes, schedules):
  ACTIVE      governs [effective_from, effective_to]
  SUPERSEDED  closed by a later row; still governs its own window, so March
              2026 keeps resolving under the method in force in March 2026
  DRAFT       an election proposed, awaiting a second person (§6.2)
  REJECTED    a proposal turned down
  VOID        a scheme or schedule replaced on the day it started: never governed
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common import clock
from common.money import to_decimal

from ..choices import (
    CUSTOM_COMPONENTS,
    DAYS_WORKED_FLAGS,
    ELECTIONS,
    GRATUITY_METHODS,
    HOURS_RANGE,
    INSURANCE_COVERAGE,
    PARTICIPATION_SCHEMES,
    PF_ELIGIBILITY,
    SCHEMES,
    FrequencyChoices,
)
from ..models import PayrollElection, PaySchedule, SchemeParticipation, SettingsAudit, SettingsEvent, StatutoryScheme
from .resolve import citation_now, elections_for

MIN_REASON = 10
GOVERNING = ("ACTIVE", "SUPERSEDED")
APP = "paysetio"


class SettingsRefused(Exception):
    def __init__(self, errors, status=422, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def _reason(text, what="a reason"):
    text = str(text or "").strip()
    if len(text) < MIN_REASON:
        raise SettingsRefused({"reason": [f"Give {what}, at least {MIN_REASON} characters ({len(text)} so far)."]})
    return text


def _date(value, field="effectiveFrom", default=None):
    from datetime import date

    if value in (None, ""):
        if default is not None:
            return default
        raise SettingsRefused({field: [f"{field} is required, YYYY-MM-DD."]}, status=400)
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise SettingsRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


def _book(on):
    """The labour rule set in force on `on`, as a view."""
    from rulebookio.book import RuleSetView, resolve

    try:
        return RuleSetView(resolve("LABOUR", on))
    except Exception:  # noqa: BLE001
        raise SettingsRefused({"effectiveFrom": [f"No labour rule set is in force on {on:%d/%m/%Y}, so the "
                                                 "election has nothing to cite."]}, status=409) from None


def _origin(company):
    """Where a preset begins: the company's own start, not a guessed joining date."""
    created = getattr(company, "created_at", None)
    return min(created.date(), clock.today()) if created else clock.today()


# ========================================================== audit and events


def audit(company, action, user=None, *, key="", scheme="", site=None, before=None, after=None, reason="",
          impact=None, effective_from=None, approver=None):
    SettingsAudit.objects.create(company=company, site=site, election_key=key, scheme_code=scheme, action=action,
                                 from_value=before, to_value=after, reason=reason or "", impact_json=impact,
                                 effective_from=effective_from, decided_by=_who(user), decided_by_name=_name(user),
                                 approved_by=_who(approver), approved_by_name=_name(approver))


ROUTES = {
    "ElectionProposed": ("PAYROLL_ELECTION_PROPOSED", "approve_payroll_election"),
    "ElectionBackdated": ("PAYROLL_ELECTION_BACKDATED", "write_payroll_election"),
    "SettingsBlockedRun": ("PAYROLL_SETTINGS_BLOCKED", "write_payroll_election"),
}


def event(company, name, *, message="", actor=None, rule_set=None, citation=None, **payload):
    """§8. Payloads carry the rule set and the citation."""
    if rule_set is not None:
        payload["ruleSetId"] = str(rule_set.uid)
    if citation:
        payload["citation"] = citation
    ev = SettingsEvent.objects.create(company=company, name=name, payload=payload)
    route = ROUTES.get(name)
    if route:
        from intakeio.services.ops import holders
        from notificationio.choices import NotificationModelKindChoices, NotificationStatusChoices
        from notificationio.services.notifications import NotificationService

        kind, perm = route
        users = {u.pk: u for u in holders(company, APP, perm)}
        users.pop(getattr(actor, "pk", None), None)
        if users:
            NotificationService.create_notification(
                status=NotificationStatusChoices.PUBLISHED, model_kind=NotificationModelKindChoices.PAYROLL_SETTINGS,
                kind=kind, message=(message or name)[:100], is_company=True, users=list(users.values()))
    return ev


# ================================================================== seeding


def ensure_settings(company):
    """The three preset elections and the four schemes, once. A preset is a
    starting point the screen states, not a decision held against the
    company: it is SEEDED, and replacing it needs no second approver."""
    on = _origin(company)
    try:
        labour = _book(clock.today())
    except SettingsRefused:  # no labour set in force: nothing to cite yet
        return
    rule_set = labour.rule_set
    for key, meta in ELECTIONS.items():
        if meta["preset"] is None:
            continue
        if PayrollElection.objects.filter(company=company, site__isnull=True, election_key=key).exists():
            continue
        preset = meta["preset"]
        PayrollElection.objects.create(
            company=company, election_key=key, value_text=None if isinstance(preset, dict) else preset,
            value_json=preset if isinstance(preset, dict) else None,
            statutory_citation=citation_now(key, labour) or meta["label"],
            rule_set=rule_set, effective_from=on, source="SEEDED",
            reason="Preset: the value the system applied before payroll settings existed.")
    for code in SCHEMES:
        if not StatutoryScheme.objects.filter(company=company, scheme_code=code).exists():
            StatutoryScheme.objects.create(company=company, scheme_code=code, applies=code == "GRATUITY",
                                           statutory_citation=_scheme_citation(code), config_json=default_config(code),
                                           effective_from=on, reason="Preset")


def default_config(code):
    return {
        "PF": {"constituted": False, "constitutionDate": None, "employeeRatePct": "8.0000",
               "employerRatePct": "8.0000", "eligibility": "ON_CONFIRMATION", "eligibilityMonths": None,
               "autoEnrol": False, "trustDeedRef": None},
        "GRATUITY": {"method": "MONTHLY_PROVISION", "fundName": None, "minServiceYears": 1},
        "GROUP_INSURANCE": {"inForce": False, "insurer": None, "policyNo": None, "renewalDate": None,
                            "coverage": "ALL_WORKERS", "sumAssured": None, "premiumMonthly": "148.0000"},
        "WPPF": {"eligibilityMonths": 6, "profitSharePct": "5.0000",
                 "distributionSplit": {"workers": 80, "welfareFund": 10, "govtFund": 10}},
    }[code]


def _scheme_citation(code):
    try:
        return _book(clock.today()).citation(SCHEMES[code]["citation"])
    except Exception:  # noqa: BLE001
        return SCHEMES[code]["label"]


# ================================================================ elections


def _site_label(site):
    return site.name if site is not None else "Company-wide"


def _scope(company, site):
    q = PayrollElection.objects.filter(company=company)
    return q.filter(site=site) if site is not None else q.filter(site__isnull=True)


def latest(company, key, site=None):
    """The open-ended governing row of exactly this scope."""
    return (_scope(company, site).filter(election_key=key, status__in=GOVERNING)
            .order_by("-effective_from").first())


def pending(company, key=None, site=None, *, any_scope=False):
    q = PayrollElection.objects.filter(company=company, status="DRAFT")
    if not any_scope:
        q = q.filter(site=site) if site is not None else q.filter(site__isnull=True)
    if key:
        q = q.filter(election_key=key)
    return q.select_related("site").order_by("-created_at")


def _pct(value, field):
    try:
        v = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise SettingsRefused({field: [f"{field} must be a number."]}) from None
    if v < 0 or v > 100:
        raise SettingsRefused({field: [f"{field} must be 0 to 100, got {v}."]})
    return v


def validate_bands(bands):
    """§3.3: contiguous, non-overlapping, covering months 0 to 11. A gap at
    month 6 means an employee with six months' service gets no bonus and no
    error."""
    if not isinstance(bands, list) or not bands:
        raise SettingsRefused({"bands": ["Give the bands, from month 0 to month 11."]})
    prev, out = -1, []
    for b in sorted(bands, key=lambda x: int(x.get("fromMonths", 0))):
        try:
            lo, hi = int(b["fromMonths"]), int(b["toMonths"])
        except (KeyError, TypeError, ValueError):
            raise SettingsRefused({"bands": ["Each band needs fromMonths and toMonths."]}) from None
        if lo != prev + 1:
            raise SettingsRefused({"bands": [f"Bonus bands must be contiguous — a gap or overlap at month {lo}."]})
        if hi < lo:
            raise SettingsRefused({"bands": [f"A band cannot end ({hi}) before it starts ({lo})."]})
        pct = _pct(b.get("pct"), "pct")
        out.append({"fromMonths": lo, "toMonths": hi, "pct": f"{pct.normalize():f}"})
        prev = hi
    if prev != 11:
        raise SettingsRefused({"bands": [f"Bonus bands must cover months 0 to 11, last band ends at {prev}."]})
    return out


def clean_value(key, value, data, hours):
    """(value_text, value_json, hours) or a 422 naming the field."""
    meta = ELECTIONS[key]
    data = data or {}
    if key == "days_worked_basis":
        flags = {f: bool(data.get(f)) for f in DAYS_WORKED_FLAGS}
        flags["present"] = True
        return None, flags, None
    allowed = [v for v, _ in meta["options"]]
    if value not in allowed:
        raise SettingsRefused({"value": [f"{meta['label']} is one of {', '.join(allowed)}."]})
    if hours not in (None, ""):
        if key != "overtime_base":
            raise SettingsRefused({"standardMonthHours": ["Standard month hours belong to the overtime base only."]})
        try:
            hours = int(hours)
        except (TypeError, ValueError):
            raise SettingsRefused({"standardMonthHours": ["Standard month hours is a whole number."]}) from None
        if not HOURS_RANGE[0] <= hours <= HOURS_RANGE[1]:
            raise SettingsRefused({"standardMonthHours": [
                f"Standard month hours must be {HOURS_RANGE[0]} to {HOURS_RANGE[1]}, got {hours}."]})
    else:
        hours = None
    js = None
    if value == "CUSTOM":
        comps = [c for c in (data.get("components") or []) if c in CUSTOM_COMPONENTS]
        if not comps:
            raise SettingsRefused({"components": ["A custom base names at least one component."]})
        js = {"components": comps}
    if key == "festival_bonus_policy" and value == "BANDED":
        js = {"bands": validate_bands(data.get("bands"))}
    return value, js, hours


def _value_of(row):
    if row is None:
        return None
    return {"value": row.value_text, "data": row.value_json, "standardMonthHours": row.standard_month_hours}


def _restatement_scope(company, effective_from):
    from employeeio.models import ProcessedPayrollPeriod

    return [p.strftime("%Y-%m") for p in ProcessedPayrollPeriod.objects.filter(
        company=company, period__gte=effective_from.replace(day=1)).values_list("period", flat=True)]


@transaction.atomic
def elect(company, key, data, *, user=None, site=None):
    """§6.2. A first election (or replacing a preset) is in force at once.
    Anything else is a proposal: a reason, the impact preview stored, and a
    second person to approve it."""
    from .consequence import preview

    if key not in ELECTIONS:
        raise SettingsRefused({"key": [f"Unknown election {key}."]}, status=404)
    value, js, hours = clean_value(key, data.get("value"), data.get("data"), data.get("standardMonthHours"))
    effective_from = _date(data.get("effectiveFrom"), default=clock.today())
    book = _book(effective_from)
    current = latest(company, key, site)
    inherited = None if site is None else latest(company, key, None)
    governing = current or inherited
    # A first election, or replacing a preset nobody chose, is in force at
    # once; changing a real election is a proposal.
    immediate = governing is None or governing.source == "SEEDED"
    if current is not None and effective_from <= current.effective_from:
        raise SettingsRefused({"effectiveFrom": [
            f"The election in force began on {current.effective_from:%d/%m/%Y}; a new one starts after it. "
            "An election is never rewritten in place."]}, status=409)
    if pending(company, key, site).exists():
        raise SettingsRefused({"key": [f"A change to the {ELECTIONS[key]['label'].lower()} is already awaiting "
                                       "approval. Approve or reject it first."]}, status=409)
    if immediate:
        reason = str(data.get("reason") or "").strip()
    else:
        reason = _reason(data.get("reason"), "a reason for changing the election")
    row = PayrollElection(company=company, site=site, election_key=key, value_text=value, value_json=js,
                          standard_month_hours=hours, statutory_citation=citation_now(key, book) or ELECTIONS[key]["label"],
                          rule_set=book.rule_set, effective_from=effective_from, reason=reason,
                          decided_by=_who(user), decided_by_name=_name(user))
    if immediate:
        row.status = "ACTIVE"
        _close(current, effective_from)
        row.save()
        audit(company, "ELECTED", user, key=key, site=site, before=_value_of(current), after=_value_of(row),
              reason=reason, effective_from=effective_from)
        event(company, "ElectionMade", actor=user, rule_set=book.rule_set, citation=row.statutory_citation,
              key=key, site=str(site.uid) if site else None, value=_value_of(row),
              effectiveFrom=effective_from.isoformat())
        _backdated(company, row, user)
        return row
    impact = preview(company, key, value, js or data.get("data"), hours=hours, site=site, on=effective_from)
    row.status = "DRAFT"
    row.impact_json = impact
    row.save()
    audit(company, "PROPOSED", user, key=key, site=site, before=_value_of(governing), after=_value_of(row),
          reason=reason, impact=impact, effective_from=effective_from)
    event(company, "ElectionProposed", actor=user, rule_set=book.rule_set, citation=row.statutory_citation,
          message=f"{_name(user) or 'Someone'} proposed a new {ELECTIONS[key]['label'].lower()}: approval needed",
          key=key, proposal=str(row.uid))
    return row


def _close(row, effective_from):
    if row is None:
        return
    row.effective_to = effective_from - timedelta(days=1)
    row.status = "SUPERSEDED"
    row.save(update_fields=["effective_to", "status", "updated_at"])


def _backdated(company, row, user):
    scope = _restatement_scope(company, row.effective_from)
    if scope:
        event(company, "ElectionBackdated", actor=user, rule_set=row.rule_set, citation=row.statutory_citation,
              message=f"{ELECTIONS[row.election_key]['label']} backdated into {len(scope)} processed period(s)",
              key=row.election_key, election=str(row.uid), restate=scope)
    return scope


@transaction.atomic
def approve(company, row, *, user=None):
    """§6.2 steps 3-7. The approver must not be the person who proposed it."""
    row = PayrollElection.objects.select_for_update().get(pk=row.pk)
    if row.status != "DRAFT":
        raise SettingsRefused({"status": ["Only a proposal awaiting approval can be approved."]}, status=409)
    if _who(user) is not None and row.decided_by_id == user.pk:
        raise SettingsRefused({"approver": ["You proposed this change, so someone else has to approve it. One "
                                            "person should not move this figure alone."]}, status=403)
    current = latest(company, row.election_key, row.site)
    if current is not None and row.effective_from <= current.effective_from:
        raise SettingsRefused({"effectiveFrom": ["The election in force has changed since this was proposed. "
                                                 "Reject it and propose again."]}, status=409)
    _close(current, row.effective_from)
    row.status = "ACTIVE"
    row.approved_by = _who(user)
    row.approved_by_name = _name(user)
    row.approved_at = timezone.now()
    try:
        row.save()
    except IntegrityError:
        raise SettingsRefused({"effectiveFrom": ["This would overlap an election already in force."]},
                              status=409) from None
    audit(company, "SUPERSEDED", row.decided_by, key=row.election_key, site=row.site,
          before=_value_of(current), after=_value_of(row), reason=row.reason, impact=row.impact_json,
          effective_from=row.effective_from, approver=user)
    event(company, "ElectionSuperseded", actor=user, rule_set=row.rule_set, citation=row.statutory_citation,
          key=row.election_key, site=str(row.site.uid) if row.site else None, value=_value_of(row),
          previous=_value_of(current), effectiveFrom=row.effective_from.isoformat())
    _backdated(company, row, user)
    return row


@transaction.atomic
def reject(company, row, *, reason, user=None):
    row = PayrollElection.objects.select_for_update().get(pk=row.pk)
    if row.status != "DRAFT":
        raise SettingsRefused({"status": ["Only a proposal awaiting approval can be rejected."]}, status=409)
    reason = _reason(reason, "a reason for rejecting it")
    row.status = "REJECTED"
    row.rejected_reason = reason
    row.approved_by = _who(user)
    row.approved_by_name = _name(user)
    row.approved_at = timezone.now()
    row.save()
    audit(company, "REJECTED", row.decided_by, key=row.election_key, site=row.site, after=_value_of(row),
          reason=reason, impact=row.impact_json, effective_from=row.effective_from, approver=user)
    return row


def election_out(row):
    return {
        "uid": str(row.uid), "key": row.election_key, "value": row.value_text, "data": row.value_json,
        "standardMonthHours": row.standard_month_hours, "citation": row.statutory_citation,
        "ruleSet": row.rule_set.version if row.rule_set_id else None, "site": _site_out(row.site),
        "effectiveFrom": row.effective_from.isoformat(),
        "effectiveTo": row.effective_to.isoformat() if row.effective_to else None, "status": row.status,
        "source": row.source, "reason": row.reason or None, "decidedBy": row.decided_by_name or None,
        "decidedByUid": str(row.decided_by.uid) if row.decided_by_id and hasattr(row.decided_by, "uid") else None,
        "approvedBy": row.approved_by_name or None,
        "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
        "rejectedReason": row.rejected_reason or None, "impact": row.impact_json,
        "createdAt": row.created_at.isoformat(),
    }


def _site_out(site):
    return {"uid": str(site.uid), "name": site.name, "code": site.code} if site is not None else None


def history(company, key, site=None):
    rows = (_scope(company, site).filter(election_key=key).select_related("rule_set", "site", "decided_by")
            .order_by("-effective_from", "-created_at"))
    return [election_out(r) for r in rows]


# ================================================================== schedule


def schedule_in_force(company, site=None, on=None):
    on = on or clock.today()
    q = (PaySchedule.objects.filter(company=company, status__in=GOVERNING, effective_from__lte=on)
         .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on)))
    own = q.filter(site=site).order_by("-effective_from").first() if site is not None else None
    return own or q.filter(site__isnull=True).order_by("-effective_from").first()


def schedule_out(s, *, site=None):
    if s is None:
        return None
    return {"uid": str(s.uid), "frequency": s.frequency, "cutoffDay": s.cutoff_day, "paymentDay": s.payment_day,
            "paymentWeekday": s.payment_weekday, "paymentDayRule": s.payment_day_rule,
            "effectiveFrom": s.effective_from.isoformat(),
            "effectiveTo": s.effective_to.isoformat() if s.effective_to else None, "site": _site_out(s.site),
            "decidedBy": s.decided_by_name or None, "reason": s.reason or None}


def deadline_check(company, site, payment_day, start=None, months=12):
    from employeeio.services.sites import default_site

    from .calendar import Calendar, check_payment_day

    start = (start or clock.today()).replace(day=1)
    ms, y, m = [], start.year, start.month
    for _ in range(months):
        ms.append(start.replace(year=y, month=m))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    cal = Calendar(site or default_site(company))
    return check_payment_day(cal, payment_day, ms)


@transaction.atomic
def set_schedule(company, data, *, user=None, site=None):
    """§3.4. The payment day is checked against s.123 when it is written:
    a payment day past the seventh working day after the wage period is
    refused, with the computed deadline in the message."""
    freq = data.get("frequency")
    if freq not in FrequencyChoices.values:
        raise SettingsRefused({"frequency": [f"Pay frequency is one of {', '.join(FrequencyChoices.values)}."]})

    def day(field, lo, hi):
        v = data.get(field)
        if v in (None, ""):
            return None
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise SettingsRefused({field: [f"{field} is a whole number."]}) from None
        if not lo <= v <= hi:
            raise SettingsRefused({field: [f"{field} is {lo} to {hi}."]})
        return v

    cutoff, pay, weekday = day("cutoffDay", 1, 31), day("paymentDay", 1, 31), day("paymentWeekday", 1, 7)
    if freq == "MONTHLY" and (cutoff is None or pay is None):
        raise SettingsRefused({"paymentDay": ["A monthly schedule needs a cut-off day and a payment day."]})
    if freq in ("WEEKLY", "FORTNIGHTLY") and weekday is None:
        raise SettingsRefused({"paymentWeekday": ["A weekly or fortnightly schedule needs a payment weekday."]})
    effective_from = _date(data.get("effectiveFrom"), default=clock.today())
    checked = unchecked = []
    if freq == "MONTHLY":
        checked, unchecked = deadline_check(company, site, pay, effective_from)
        late = [c for c in checked if c["late"]]
        if late:
            first = late[0]
            raise SettingsRefused({"paymentDay": [
                f"Day {pay} is after the s.123 deadline: wages for {first['month']} must be paid by "
                f"{_dmy(first['deadline'])}, the seventh working day after {_dmy(first['wagePeriodEnd'])} on this "
                f"establishment's calendar. {len(late)} of the next {len(checked)} months would be late."]},
                detail={"late": late})
        if not checked:
            raise SettingsRefused({"paymentDay": [
                "No published holiday calendar covers the coming months, so the s.123 deadline cannot be computed. "
                "Publish the establishment's calendar first."]}, status=409)
    q = PaySchedule.objects.filter(company=company, status__in=GOVERNING)
    q = q.filter(site=site) if site is not None else q.filter(site__isnull=True)
    current = q.order_by("-effective_from").first()
    if current is not None and effective_from < current.effective_from:
        raise SettingsRefused({"effectiveFrom": [
            f"The schedule in force began on {current.effective_from:%d/%m/%Y}; a new one starts on or after it."]},
            status=409)
    reason = _reason(data.get("reason"), "a reason for changing the schedule") if current else ""
    before = schedule_out(current)
    if current is not None:
        if current.effective_from == effective_from:
            current.status = "VOID"
            current.save(update_fields=["status", "updated_at"])
        else:
            current.effective_to = effective_from - timedelta(days=1)
            current.status = "SUPERSEDED"
            current.save(update_fields=["effective_to", "status", "updated_at"])
    s = PaySchedule.objects.create(company=company, site=site, frequency=freq, cutoff_day=cutoff, payment_day=pay,
                                   payment_weekday=weekday, effective_from=effective_from, reason=reason,
                                   decided_by=_who(user), decided_by_name=_name(user))
    audit(company, "SCHEDULE_CHANGED", user, site=site, before=before, after=schedule_out(s), reason=reason,
          effective_from=effective_from)
    event(company, "ScheduleChanged", actor=user, frequency=freq, paymentDay=pay, cutoffDay=cutoff,
          effectiveFrom=effective_from.isoformat())
    return s, {"checked": checked, "unchecked": unchecked}


def _dmy(iso):
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


# =================================================================== schemes


def scheme_in_force(company, code, on=None):
    on = on or clock.today()
    return (StatutoryScheme.objects.filter(company=company, scheme_code=code, status__in=GOVERNING,
                                           effective_from__lte=on, site__isnull=True)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on))
            .select_related("expense_account", "liability_account").order_by("-effective_from").first())


def scheme_config(company, code, on=None):
    s = scheme_in_force(company, code, on)
    return (s.config_json or {}) if s else default_config(code)


def scheme_applies(company, code, on=None):
    s = scheme_in_force(company, code, on)
    return bool(s and s.applies)


def _gl(a):
    if a is None:
        return None
    return {"uid": str(a.uid), "code": a.code or "", "title": a.title, "label": f"{a.code} · {a.title}" if a.code else a.title}


def scheme_out(s):
    if s is None:
        return None
    meta = SCHEMES[s.scheme_code]
    return {"uid": str(s.uid), "code": s.scheme_code, "label": meta["label"], "bn": meta["bn"], "applies": s.applies,
            "citation": s.statutory_citation, "config": s.config_json, "expense": _gl(s.expense_account),
            "liability": _gl(s.liability_account), "hasLiability": meta["liability"] is not None,
            "effectiveFrom": s.effective_from.isoformat(),
            "effectiveTo": s.effective_to.isoformat() if s.effective_to else None,
            "decidedBy": s.decided_by_name or None, "reason": s.reason or None,
            "suggested": {"expense": " · ".join(meta["expense"]),
                          "liability": " · ".join(meta["liability"]) if meta["liability"] else None}}


def _rate(value, field):
    """Rates are decimal strings at four places, never JSON numbers (§3.6)."""
    v = _pct(value, field)
    return f"{v.quantize(Decimal('0.0001'))}"


def clean_config(code, config, old):
    c = {**old, **(config or {})}
    if code == "PF":
        c["employeeRatePct"] = _rate(c.get("employeeRatePct"), "employeeRatePct")
        c["employerRatePct"] = _rate(c.get("employerRatePct"), "employerRatePct")
        if c.get("eligibility") not in PF_ELIGIBILITY:
            raise SettingsRefused({"eligibility": [f"PF eligibility is one of {', '.join(PF_ELIGIBILITY)}."]})
        if c["eligibility"] == "AFTER_MONTHS":
            try:
                c["eligibilityMonths"] = int(c.get("eligibilityMonths"))
            except (TypeError, ValueError):
                raise SettingsRefused({"eligibilityMonths": ["Give the months of service before joining the fund."]}) from None
        else:
            c["eligibilityMonths"] = None
        c["constituted"] = bool(c.get("constituted"))
        c["autoEnrol"] = bool(c.get("autoEnrol"))
        if c["constituted"] and not c.get("constitutionDate"):
            raise SettingsRefused({"constitutionDate": [
                "A provident fund is a trust (s.264): give the date it was constituted — contributions are payable "
                "from it."]})
        if c.get("constitutionDate"):
            c["constitutionDate"] = _date(c["constitutionDate"], "constitutionDate").isoformat()
    elif code == "GRATUITY":
        if c.get("method") not in GRATUITY_METHODS:
            raise SettingsRefused({"method": [f"Accrual is one of {', '.join(GRATUITY_METHODS)}."]})
        if c["method"] == "FUNDED_SCHEME" and not str(c.get("fundName") or "").strip():
            raise SettingsRefused({"fundName": ["A funded scheme names the trust that holds it."]})
        try:
            c["minServiceYears"] = int(c.get("minServiceYears") or 1)
        except (TypeError, ValueError):
            raise SettingsRefused({"minServiceYears": ["Minimum service is a whole number of years."]}) from None
    elif code == "GROUP_INSURANCE":
        if c.get("coverage") not in INSURANCE_COVERAGE:
            raise SettingsRefused({"coverage": [f"Coverage is one of {', '.join(INSURANCE_COVERAGE)}."]})
        c["inForce"] = bool(c.get("inForce"))
        if c.get("renewalDate"):
            c["renewalDate"] = _date(c["renewalDate"], "renewalDate").isoformat()
        if c.get("premiumMonthly") not in (None, ""):
            try:
                c["premiumMonthly"] = f"{to_decimal(str(c['premiumMonthly'])).quantize(Decimal('0.0001'))}"
            except Exception:  # noqa: BLE001
                raise SettingsRefused({"premiumMonthly": ["The premium is an amount."]}) from None
    elif code == "WPPF":
        c["profitSharePct"] = _rate(c.get("profitSharePct"), "profitSharePct")
        try:
            c["eligibilityMonths"] = int(c.get("eligibilityMonths") or 6)
        except (TypeError, ValueError):
            raise SettingsRefused({"eligibilityMonths": ["Eligibility is a whole number of months."]}) from None
    return c


RATE_KEYS = {"PF": ("employeeRatePct", "employerRatePct"), "WPPF": ("profitSharePct",),
             "GROUP_INSURANCE": ("premiumMonthly",)}


@transaction.atomic
def update_scheme(company, code, data, *, user=None):
    """§6.5. A change supersedes the scheme from a date; changing the PF rate
    does not restate past contributions."""
    if code not in SCHEMES:
        raise SettingsRefused({"code": [f"Unknown scheme {code}."]}, status=404)
    ensure_settings(company)
    effective_from = _date(data.get("effectiveFrom"), default=clock.today())
    current = scheme_in_force(company, code, effective_from) or (
        StatutoryScheme.objects.filter(company=company, scheme_code=code, status__in=GOVERNING)
        .order_by("-effective_from").first())
    old = current.config_json if current else default_config(code)
    config = clean_config(code, data.get("config"), old)
    applies = bool(data["applies"]) if "applies" in data else bool(current and current.applies)
    if current and applies == current.applies and config == current.config_json:
        return current
    if current and effective_from < current.effective_from:
        raise SettingsRefused({"effectiveFrom": [
            f"The scheme in force began on {current.effective_from:%d/%m/%Y}; a change starts on or after it."]},
            status=409)
    reason = _reason(data.get("reason"), "a reason for the change")
    if current is not None:
        if current.effective_from == effective_from:
            current.status = "VOID"
            current.save(update_fields=["status", "updated_at"])
        else:
            current.effective_to = effective_from - timedelta(days=1)
            current.status = "SUPERSEDED"
            current.save(update_fields=["effective_to", "status", "updated_at"])
    s = StatutoryScheme.objects.create(
        company=company, scheme_code=code, applies=applies, statutory_citation=_scheme_citation(code),
        config_json=config, expense_account=current.expense_account if current else None,
        liability_account=current.liability_account if current else None, effective_from=effective_from,
        reason=reason, decided_by=_who(user), decided_by_name=_name(user))
    before = scheme_out(current)
    if current is None or applies != current.applies:
        action, name = ("SCHEME_ENABLED", "SchemeEnabled") if applies else ("SCHEME_DISABLED", "SchemeDisabled")
    elif any(old.get(k) != config.get(k) for k in RATE_KEYS.get(code, ())):
        action, name = "RATE_CHANGED", "SchemeRateChanged"
    else:
        action, name = "SCHEME_CHANGED", "SchemeChanged"
    audit(company, action, user, scheme=code, before=before and {"applies": before["applies"], "config": before["config"]},
          after={"applies": s.applies, "config": s.config_json}, reason=reason, effective_from=effective_from)
    event(company, name, actor=user, citation=s.statutory_citation, scheme=code, applies=applies,
          effectiveFrom=effective_from.isoformat(),
          rates={k: config.get(k) for k in RATE_KEYS.get(code, ())})
    return s


@transaction.atomic
def map_scheme_gl(company, code, *, expense=None, liability=None, fields=(), user=None):
    """Mapping is not a rate change: it is set on the scheme in force."""
    s = scheme_in_force(company, code)
    if s is None:
        raise SettingsRefused({"code": [f"No {code} scheme in force."]}, status=404)
    if "liability" in fields and liability is not None and code == "GROUP_INSURANCE":
        raise SettingsRefused({"liability": [
            "Group insurance has no liability account: a premium is paid, not accrued. A liability here models it "
            "as a provision, which it is not."]})
    before = {"expense": _gl(s.expense_account), "liability": _gl(s.liability_account)}
    for f, acc in (("expense", expense), ("liability", liability)):
        if f in fields:
            if acc is not None and acc.company_id != company.pk:
                raise SettingsRefused({f: ["Not an account of this company."]}, status=404)
            setattr(s, f"{f}_account", acc)
    s.save(update_fields=["expense_account", "liability_account", "updated_at"])
    audit(company, "GL_MAPPED", user, scheme=code, before=before,
          after={"expense": _gl(s.expense_account), "liability": _gl(s.liability_account)})
    return s


def create_scheme_accounts(company, codes=None, *, user=None):
    """Create the scheme accounts that are missing in the company's chart of
    accounts (5xxx expense, 2xxx liability) and map them."""
    from accounts.models import ChartOfAccount

    ensure_settings(company)
    made, mapped = [], []
    for code, meta in SCHEMES.items():
        if codes and code not in codes:
            continue
        s = scheme_in_force(company, code)
        if s is None:
            continue
        want = {}
        for f, kind in (("expense", "EXPENSE"), ("liability", "LIABILITY")):
            spec = meta[f]
            if spec is None or getattr(s, f"{f}_account_id"):
                continue
            num, title = spec
            acc = ChartOfAccount.objects.filter(company=company, title__iexact=title).exclude(status="REMOVED").first()
            if acc is None:
                acc = ChartOfAccount.objects.create(company=company, title=title, code=num, kind=kind,
                                                    status="ACTIVE", currency="BDT")
                made.append(f"{num} · {title}")
            want[f] = acc
        if want:
            map_scheme_gl(company, code, expense=want.get("expense"), liability=want.get("liability"),
                          fields=tuple(want), user=user)
            mapped.append(code)
    return {"created": made, "mapped": mapped}


# ============================================================= participation


def participation_in_force(employee, code, on=None):
    on = on or clock.today()
    return (SchemeParticipation.objects.filter(employee=employee, scheme_code=code, enrolled=True,
                                               enrolled_on__lte=on)
            .filter(Q(opted_out_on__isnull=True) | Q(opted_out_on__gt=on)).order_by("-enrolled_on").first())


def open_participation(employee, code):
    return SchemeParticipation.objects.filter(employee=employee, scheme_code=code, opted_out_on__isnull=True).first()


def pf_eligible_from(employee, config):
    """The date the employee becomes eligible for the fund, or None if the
    record does not say."""
    from employeeio.services.profile import add_months

    rule = config.get("eligibility")
    if not employee.doj:
        return None
    if rule == "ON_JOINING":
        return employee.doj
    if rule == "AFTER_MONTHS":
        return add_months(employee.doj, int(config.get("eligibilityMonths") or 0))
    # ON_CONFIRMATION
    if employee.worker_category == "PROBATIONER":
        return employee.probation_end
    return employee.probation_end or employee.doj


def participation_out(p):
    return {"uid": str(p.uid), "scheme": p.scheme_code, "enrolledOn": p.enrolled_on.isoformat(),
            "optedOutOn": p.opted_out_on.isoformat() if p.opted_out_on else None,
            "optOutReason": p.opt_out_reason or None,
            "employeeRatePct": f"{p.override_rate_pct.normalize():f}" if p.override_rate_pct is not None else None,
            "employerRatePct": (f"{p.override_employer_rate_pct.normalize():f}"
                                if p.override_employer_rate_pct is not None else None),
            "decidedBy": p.decided_by_name or None}


@transaction.atomic
def enrol(company, employee, code, *, on=None, employee_rate=..., employer_rate=..., user=None, check=True):
    if code not in PARTICIPATION_SCHEMES:
        raise SettingsRefused({"scheme": [f"{code} has no per-employee enrolment."]})
    on = on or clock.today()
    if check and code == "PF":
        if not scheme_applies(company, "PF", on) or not scheme_config(company, "PF", on).get("constituted"):
            raise SettingsRefused({"pf_member": [
                "No provident fund is constituted for this company, so membership cannot be switched on."]})
        start = pf_eligible_from(employee, scheme_config(company, "PF", on))
        if start is not None and on < start:
            raise SettingsRefused({"pf_member": [
                f"Not yet eligible for the provident fund: the fund's rule ("
                f"{scheme_config(company, 'PF', on)['eligibility'].replace('_', ' ').lower()}) makes "
                f"{employee.name_en} eligible from {start:%d/%m/%Y}."]})
    current = open_participation(employee, code)
    fund = scheme_config(company, "PF", on) if code == "PF" else {}

    def own(v, key):
        """A member's own rate; the fund's rate is not an override."""
        if v in (None, "", ...):
            return None
        v = _pct(v, key)
        return None if fund.get(key) and v == Decimal(fund[key]) else v

    if current is not None:
        changed = False
        for attr, v, key in (("override_rate_pct", employee_rate, "employeeRatePct"),
                             ("override_employer_rate_pct", employer_rate, "employerRatePct")):
            if v is not ...:
                v = own(v, key)
                if getattr(current, attr) != v:
                    setattr(current, attr, v)
                    changed = True
        if changed:
            current.save()
            audit(company, "RATE_CHANGED", user, scheme=code, after={"employee": employee.code,
                                                                     **participation_out(current)})
        return current
    p = SchemeParticipation.objects.create(
        company=company, employee=employee, scheme_code=code, enrolled_on=on,
        override_rate_pct=own(employee_rate, "employeeRatePct"),
        override_employer_rate_pct=own(employer_rate, "employerRatePct"),
        decided_by=_who(user), decided_by_name=_name(user))
    audit(company, "ENROLLED", user, scheme=code, after={"employee": employee.code, **participation_out(p)},
          effective_from=on)
    return p


@transaction.atomic
def opt_out(company, employee, code, *, on=None, reason, user=None):
    p = open_participation(employee, code)
    if p is None:
        return None
    on = on or clock.today()
    reason = str(reason or "").strip()
    if not reason:
        raise SettingsRefused({"optOutReason": [
            f"Give the reason {employee.name_en} is leaving the {SCHEMES[code]['label'].lower()}: an opt-out "
            "carries one."]})
    if on < p.enrolled_on:
        on = p.enrolled_on
    p.opted_out_on = on
    p.opt_out_reason = reason
    p.save()
    audit(company, "OPTED_OUT", user, scheme=code, after={"employee": employee.code, **participation_out(p)},
          reason=reason, effective_from=on)
    return p


def auto_enrol(company, *, on=None, apply=False, user=None):
    """PF auto-enrolment: every employee eligible under the fund's rule and
    not yet a member. A preview unless `apply`."""
    from employeeio.models import Employee

    on = on or clock.today()
    cfg = scheme_config(company, "PF", on)
    if not scheme_applies(company, "PF", on) or not cfg.get("constituted"):
        return {"eligible": [], "enrolled": 0, "message": "No provident fund is constituted."}
    members = set(SchemeParticipation.objects.filter(company=company, scheme_code="PF", opted_out_on__isnull=True)
                  .values_list("employee_id", flat=True))
    out = []
    for e in (Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
              .exclude(separated_on__lt=on).exclude(pk__in=members)):
        start = pf_eligible_from(e, cfg)
        if start is not None and start <= on:
            out.append(e)
    if apply:
        for e in out:
            enrol(company, e, "PF", on=on, user=user, check=False)
    return {"eligible": [{"code": e.code, "nameEn": e.name_en} for e in out], "enrolled": len(out) if apply else 0}


# ================================================================ readiness


def readiness(company, site=None, period=None):
    """§4.2 `assertRunnable` as data. A refusal, not a warning: a run on an
    unanswered proration method produces part-month figures by an undeclared
    method, and nobody can say which."""
    from .calendar import month_bounds

    period = (period or clock.today()).replace(day=1)
    _, end = month_bounds(period)
    ensure_settings(company)
    blockers = []
    for key, r in elections_for(company, site, end).items():
        if not r.answered:
            meta = ELECTIONS[key]
            cite = citation_now(key)
            blockers.append({"kind": "UNANSWERED_ELECTION", "key": key, "citation": cite,
                             "message": f"The {meta['label'].lower()} has not been elected. "
                                        f"{meta['governs'][0].upper()}{meta['governs'][1:]} cannot be computed."})
    for code in SCHEMES:
        s = scheme_in_force(company, code, end)
        if s is not None and s.applies and s.expense_account_id is None:
            blockers.append({"kind": "UNMAPPED_SCHEME", "scheme": code,
                             "message": f"{SCHEMES[code]['label']} applies but has no expense account — the journal "
                                        "cannot post."})
    sched = schedule_in_force(company, site, end)
    if sched is None:
        blockers.append({"kind": "NO_SCHEDULE", "message": "No pay schedule is set: the s.123 deadline cannot be "
                                                           "checked."})
    elif sched.frequency == "MONTHLY":
        try:
            checked, unchecked = deadline_check(company, site, sched.payment_day, period, months=1)
        except Exception:  # noqa: BLE001
            checked, unchecked = [], [period.strftime("%Y-%m")]
        for c in checked:
            if c["late"]:
                blockers.append({"kind": "PAYMENT_AFTER_DEADLINE", "deadline": c["deadline"],
                                 "message": f"Payment on {_dmy(c['paymentDate'])} is after the s.123 deadline of "
                                            f"{_dmy(c['deadline'])}."})
        if unchecked:
            blockers.append({"kind": "NO_CALENDAR", "message": f"No published holiday calendar for {period.year}: "
                                                               "the s.123 deadline cannot be computed."})
    return {"runnable": not blockers, "period": period.strftime("%Y-%m"), "blockers": blockers}


def assert_runnable(company, site=None, period=None, *, user=None):
    out = readiness(company, site, period)
    if not out["runnable"]:
        event(company, "SettingsBlockedRun", actor=user, message=f"Payroll for {out['period']} blocked by settings",
              period=out["period"], blockers=out["blockers"])
        raise SettingsRefused({"settings": [b["message"] for b in out["blockers"]]}, status=409, detail=out)
    return out


# ================================================================ changelog


def changelog(company, *, key=None, scheme=None, limit=200):
    q = SettingsAudit.objects.filter(company=company).select_related("site")
    if key:
        q = q.filter(election_key=key)
    if scheme:
        q = q.filter(scheme_code=scheme)
    return [{"uid": str(a.uid), "action": a.action, "label": a.get_action_display(), "key": a.election_key or None,
             "scheme": a.scheme_code or None, "site": _site_out(a.site), "from": a.from_value, "to": a.to_value,
             "reason": a.reason or None, "impact": a.impact_json,
             "effectiveFrom": a.effective_from.isoformat() if a.effective_from else None,
             "decidedBy": a.decided_by_name or None, "approvedBy": a.approved_by_name or None,
             "at": a.created_at.isoformat()} for a in q[:limit]]
