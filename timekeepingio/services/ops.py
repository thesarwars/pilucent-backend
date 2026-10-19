"""Attendance operations (§9): the grid, a day, month close, compliance, and
every write -- adjustments, exception decisions, holiday-working
confirmation, lock and reopen, punch import, shifts and the calendar.

Every write refuses on a locked period (§1.8) and goes to the audit.
"""

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common import clock
from common.money import money_str, round_to_paisa
from employeeio.services.salary_access import actor_role
from employeeio.services.sites import site_of
from employeeio.services.validation import validate_reason

from ..choices import AttendanceAuditActionChoices as A
from ..choices import CalendarStatusChoices, CreditKindChoices, DayStatusChoices, ExceptionStateChoices
from ..choices import ExceptionKindChoices as K
from ..choices import PeriodStatusChoices, PunchSourceChoices, QuarantineReasonChoices, SETTABLE_STATUSES
from ..models import (
    Adjustment,
    CompensatoryCredit,
    DaySnapshot,
    ExceptionDecision,
    HolidayCalendar,
    HolidayCalendarDay,
    Punch,
    PunchQuarantine,
    Shift,
    ShiftAssignment,
)
from .base import (
    DHAKA,
    AttendanceRefused,
    CalendarMissing,
    actor_name,
    audit,
    business_date_and_minute,
    current_assignment,
    ensure_period,
    locked_months,
    month_end,
    month_start,
    period_phase,
    refuse_if_locked,
    shift_on,
    site_employees,
    assignments_by_employee,
)
from .engine import EXCEPTIONS, HOLIDAY_WORK, Rules, citation, days_worked_for_accrual, hhmm
from .window import Window, iso_weeks

DOW = "MTWTFSS"


def _reason(text, what="a reason"):
    try:
        return validate_reason(text)
    except ValidationError as exc:
        raise AttendanceRefused({"reason": [f"Give {what}. {' '.join(exc.messages)}"]}) from None


def rules_of(period):
    return Rules.from_rule_set(period.rule_set)


def elections_of(company, site=None, on=None):
    """The payroll elections attendance reads (payroll settings §4.1), as
    resolved for the site on `on`. Elected in Payroll settings, not here."""
    from paysetio.services.resolve import elections_for

    r = elections_for(company, site, on or clock.today())
    ot, worked = r["overtime_base"], r["days_worked_basis"]
    return {
        "overtimeBase": ot.value,
        "overtimeComponents": (ot.data or {}).get("components") if ot.value == "CUSTOM" else None,
        "standardMonthHours": ot.hours,
        "daysWorked": {k: bool(v) for k, v in (worked.data or {}).items()} if worked.answered else None,
        "answered": {"overtimeBase": ot.answered, "daysWorked": worked.answered},
        "citations": {"overtimeBase": ot.as_dict()["citation"], "daysWorked": worked.as_dict()["citation"]},
    }


def period_out(period, today=None):
    return {
        "uid": str(period.uid),
        "month": period.period_month.strftime("%Y-%m"),
        "status": period_phase(period, today),
        "ruleSet": period.rule_set.version,
        "lockedAt": period.locked_at.isoformat() if period.locked_at else None,
        "lockedBy": actor_name(period.locked_by) or None,
        "reopenedAt": period.reopened_at.isoformat() if period.reopened_at else None,
        "reopenReason": period.reopen_reason or None,
        "stage": period.stage,
        "acknowledgeReason": period.acknowledge_reason or None,
        "exceptionsAcknowledged": period.exceptions_acknowledged,
        "payrollRun": period.payroll_run_ref or None,
        "payrollProcessedOn": period.payroll_processed_on.isoformat() if period.payroll_processed_on else None,
        "payrollInvalidated": period.payroll_invalidated_ref or None,
    }


def exception_out(kind, rules, decision=None):
    label, severity, blocks, terminal, remedy, action, _ = EXCEPTIONS[kind]
    return {
        "kind": kind, "label": label, "severity": severity, "blocksClose": blocks, "terminal": terminal,
        "remedy": remedy, "action": action, "citation": citation(kind, rules),
        "decision": None if decision is None else {
            "state": decision.state, "outcome": decision.outcome or None, "resolution": decision.resolution or None,
            "by": decision.decided_by_name or None, "at": decision.created_at.isoformat(),
        },
    }


# ======================================================================= grid


def grid(company, site, month, *, dept=None, q="", exceptions_only=False, page=1, limit=100):
    """§9.1: the month for the filtered roster, row per employee with a dense
    array of days. Paginated by employee, never by day."""
    period = ensure_period(company, site, month)
    rules = rules_of(period)
    first, last = month, month_end(month)
    everyone = site_employees(company, site)
    roster_empty = not everyone.exists()
    employees = everyone
    if dept:
        employees = employees.filter(department__uid=dept)
    if q:
        employees = employees.filter(Q(code__icontains=q) | Q(name_en__icontains=q) | Q(name_bn__icontains=q))
    employees = list(employees)
    w = Window(company, site, employees, first, last, rules)

    rows, open_total, blocking_total = [], 0, 0
    for e in employees:
        cells, ot, late, opened, kinds, no_shift = [], 0, 0, 0, set(), False
        for d in w.days:
            r = w.record(e, d)
            open_kinds = w.open_kinds(e, d)
            blocking = [k for k in open_kinds if EXCEPTIONS[k][2]]
            cells.append({"s": r.status, "a": r.adjusted, "x": open_kinds, "b": bool(blocking), "p": r.pending,
                          "n": r.no_shift, "ot": r.overtime})
            ot += r.overtime
            late += r.late
            opened += len(open_kinds)
            blocking_total += len(blocking)
            kinds.update(open_kinds)
            no_shift = no_shift or r.no_shift
        open_total += opened
        shift = shift_on(w.assignments.get(e.pk), min(max(w.today, first), last))
        rows.append({
            "code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn,
            "department": e.department.title if e.department else None,
            "shift": {"code": shift.code, "label": shift.label, "start": hhmm(shift.start_min),
                      "end": hhmm(shift.end_min)} if shift else None,
            "noShift": no_shift, "otMinutes": ot, "lateMinutes": late,
            "openExceptions": opened, "exceptionKinds": sorted(kinds), "days": cells,
        })
    if exceptions_only:
        rows = [r for r in rows if r["openExceptions"]]
    count = len(rows)
    limit = max(1, min(int(limit or 100), 300))
    page = max(1, int(page or 1))
    rows = rows[(page - 1) * limit: page * limit]
    days = []
    for d in w.days:
        kind, name = w.kind_of(d)
        days.append({"date": d.isoformat(), "num": d.day, "dow": DOW[d.weekday()], "kind": kind, "name": name})
    return {
        "period": period_out(period), "site": {"uid": str(site.uid), "name": site.name},
        "days": days, "rows": rows, "count": count, "page": page, "pages": max(1, -(-count // limit)),
        "rosterEmpty": roster_empty,
        "counts": {"exceptions": open_total, "blocking": blocking_total},
        "rules": {"version": rules.version, "confidence": rules.confidence},
    }


# ======================================================================== day


def hourly_ot_rate(employee, d, rules):
    """§6.2: the elected overtime base ÷ the standard month hours × the
    multiplier, on the ACTUAL structure in force -- never an approximation
    from gross. None with no structure; {"unanswered": ...} when the
    overtime base has not been elected."""
    from employeeio.services.salary import structure_in_force
    from paysetio.services.resolve import ElectionUnanswered, election, overtime_base

    structure = structure_in_force(employee, d)
    if structure is None:
        return None
    r = election(employee.company, "overtime_base", d, site_of(employee))
    try:
        base, _, label = overtime_base(structure, r)
    except ElectionUnanswered as exc:
        return {"unanswered": True, "message": exc.message}
    hours = r.hours or rules.standard_month_hours
    rate = round_to_paisa(base / Decimal(hours) * rules.overtime_multiplier)
    return {
        "base": money_str(base),
        "basis": f"{label} ÷ {hours} × {rules.overtime_multiplier}",
        "rate": money_str(rate),
        "rateValue": rate,
    }


def day_detail(company, employee, d, *, figures):
    site = site_of(employee)
    period = ensure_period(company, site, month_start(d))
    rules = rules_of(period)
    w = Window(company, site, [employee], d, d, rules)
    r = w.record(employee, d)
    shift = shift_on(w.assignments.get(employee.pk), d)
    kind, holiday_name = w.kind_of(d)
    punches = [{
        "at": p.punched_at.astimezone(DHAKA).strftime("%Y-%m-%d %H:%M"), "direction": p.direction,
        "source": p.source, "device": p.device_id if p.source == "DEVICE" else None,
    } for p in Punch.objects.filter(employee=employee, business_date=d, void__isnull=True).order_by("punched_at")]
    adjustments = [{
        "uid": str(a.uid), "live": a.is_live, "removed": a.removed, "newStatus": a.new_status or None,
        "inTime": hhmm(a.in_time_min) if a.in_time_min is not None else None,
        "outTime": hhmm(a.out_time_min) if a.out_time_min is not None else None,
        "inTimeMin": a.in_time_min, "outTimeMin": a.out_time_min,
        "reason": a.reason, "note": a.note or None, "by": a.actor_name or None, "at": a.created_at.isoformat(),
    } for a in Adjustment.objects.filter(employee=employee, business_date=d).order_by("-created_at")]
    out = {
        "employee": {"code": employee.code, "nameEn": employee.name_en, "nameBn": employee.name_bn},
        "date": d.isoformat(), "period": period_out(period), "dayKind": kind, "holidayName": holiday_name,
        "shift": None if shift is None else {
            "code": shift.code, "label": shift.label, "start": hhmm(shift.start_min), "end": hhmm(shift.end_min),
            "standardMinutes": shift.standard_minutes, "unpaidBreak": shift.unpaid_break_minutes,
            "grace": shift.late_grace_minutes, "otStartsAfter": shift.ot_starts_after_min,
            "requiresPreApproval": shift.requires_pre_approval,
        },
        "punches": punches,
        "computed": {
            "status": r.status, "worked": r.worked, "overtime": r.overtime, "late": r.late,
            "inTime": hhmm(r.in_min) if r.in_min is not None else None,
            "outTime": hhmm(r.out_min) if r.out_min is not None else None,
            "adjusted": r.adjusted, "pending": r.pending, "noShift": r.no_shift, "steps": r.steps,
        },
        "exceptions": [exception_out(k, rules, w.decision(employee, d, k)) for k in r.exceptions],
        "adjustments": adjustments,
        "otRate": None, "otCost": None, "masked": not figures,
        "settable": list(SETTABLE_STATUSES),
    }
    if figures:
        rate = hourly_ot_rate(employee, d, rules)
        if rate is not None and rate.get("unanswered"):
            out["otRate"] = rate
        elif rate is not None:
            out["otCost"] = money_str(round_to_paisa(rate.pop("rateValue") * r.overtime / 60))
            out["otRate"] = rate
    return out


# ================================================================= exceptions


def exceptions_list(company, site, month, *, include_decided=False):
    """§9 view: every exception in the month, open first, with its remedy
    and citation. Decided ones are listed on request, so an acknowledged
    breach can still be read with its reason."""
    period = ensure_period(company, site, month)
    rules = rules_of(period)
    employees = list(site_employees(company, site))
    w = Window(company, site, employees, month, month_end(month), rules)
    rows = []
    for e in employees:
        for d in w.days:
            r = w.record(e, d)
            for k in r.exceptions:
                x = w.decision(e, d, k)
                if x is not None and not include_decided:
                    continue
                rows.append({
                    "code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn,
                    "department": e.department.title if e.department else None,
                    "date": d.isoformat(), "status": r.status, "worked": r.worked, "overtime": r.overtime,
                    "late": r.late, "inTime": hhmm(r.in_min) if r.in_min is not None else None,
                    "outTime": hhmm(r.out_min) if r.out_min is not None else None,
                    "actions": list({**ADJUSTING.get(k, {}), **DECIDING.get(k, {})}) or (
                        ["ACKNOWLEDGE"] if k == K.DAILY_LIMIT_EXCEEDED else []),
                    **exception_out(k, rules, x),
                })
    severity = {"HIGH": 0, "MEDIUM": 1}
    rows.sort(key=lambda row: (row["decision"] is not None, severity.get(row["severity"], 2), row["date"],
                               row["code"]))
    open_rows = [row for row in rows if row["decision"] is None]
    return {
        "period": period_out(period), "rows": rows, "count": len(open_rows),
        "blocking": sum(1 for row in open_rows if row["blocksClose"]),
        "byKind": {k: sum(1 for row in open_rows if row["kind"] == k) for k in EXCEPTIONS},
    }


# ================================================================ month close


def close_summary(company, site, month):
    """§10: the gates, the totals, days worked for accrual and the holiday
    working to confirm. Recomputable at any time; writes nothing."""
    period = ensure_period(company, site, month)
    rules = rules_of(period)
    today = clock.today()
    elections = elections_of(company, site, month_end(month))
    out = {"period": period_out(period, today), "elections": elections, "rules": {"version": rules.version,
                                                                                    "confidence": rules.confidence}}
    employees = list(site_employees(company, site))
    try:
        w = Window(company, site, employees, month, month_end(month), rules, today=today)
    except CalendarMissing as exc:
        out.update(gates=[{"key": "calendar", "label": exc.errors["calendar"][0], "count": 1, "blocks": True,
                           "rows": []}], canLock=False, totals=None, employees=[], holidayWork=[])
        return out

    high, holiday_work, medium, no_shift, people = [], [], [], [], []
    totals = {k: 0.0 for k in ("present", "halfDay", "absent", "leave", "lwp", "holiday", "weekly", "onDuty",
                                "daysWorked")}
    totals.update(overtimeMinutes=0, lateMinutes=0, workedMinutes=0)
    for e in employees:
        recs = w.records(e)
        mine = {k: 0 for k in ("present", "halfDay", "absent", "leave", "lwp", "holiday", "weekly", "onDuty")}
        for r in recs:
            key = {"PRESENT": "present", "PRESENT_OT": "present", "HALF_DAY": "halfDay", "ABSENT": "absent",
                   "ON_LEAVE": "leave", "LEAVE_WITHOUT_PAY": "lwp", "HOLIDAY": "holiday",
                   "WEEKLY_HOLIDAY": "weekly", "ON_DUTY": "onDuty"}.get(r.status)
            if key:
                mine[key] += 1
            if r.no_shift and e.code not in no_shift:
                no_shift.append(e.code)
            for k in w.open_kinds(e, r.day):
                row = {"code": e.code, "nameEn": e.name_en, "date": r.day.isoformat(), "kind": k,
                       "label": EXCEPTIONS[k][0], "worked": r.worked}
                if k in HOLIDAY_WORK:
                    holiday_work.append(row)
                elif EXCEPTIONS[k][1] == "HIGH":
                    high.append(row)
                else:
                    medium.append(row)
        worked_days = days_worked_for_accrual(recs, elections["daysWorked"]) if elections["daysWorked"] else None
        ot = sum(r.overtime for r in recs)
        late = sum(r.late for r in recs)
        worked = sum(r.worked for r in recs)
        for k, v in mine.items():
            totals[k] += v
        totals["daysWorked"] += worked_days or 0
        totals["overtimeMinutes"] += ot
        totals["lateMinutes"] += late
        totals["workedMinutes"] += worked
        people.append({"code": e.code, "nameEn": e.name_en, **mine, "daysWorked": worked_days,
                       "overtimeMinutes": ot, "lateMinutes": late, "workedMinutes": worked})

    ended = month_end(month) < today
    gates = [
        {"key": "monthEnded", "label": "The month has ended" if ended else f"{month:%B %Y} has not ended yet",
         "count": 0 if ended else 1, "blocks": True, "rows": []},
        {"key": "high", "label": "Unresolved exceptions that block payroll", "count": len(high), "blocks": True,
         "rows": high},
        {"key": "holidayWork", "label": "Holiday working not yet confirmed", "count": len(holiday_work),
         "blocks": True, "rows": holiday_work},
        {"key": "noShift", "label": "Employees with no shift for part of the month", "count": len(no_shift),
         "blocks": True, "rows": [{"code": c} for c in no_shift]},
        {"key": "medium", "label": "Open lateness and overtime to review", "count": len(medium), "blocks": False,
         "rows": medium},
    ]
    locked = period.status == PeriodStatusChoices.LOCKED
    out.update(
        gates=gates, totals=totals, employees=people, holidayWork=holiday_work,
        canLock=not locked and not any(g["blocks"] and g["count"] for g in gates),
        accrualCitation="Bangladesh Labour Act 2006, s.117",
    )
    return out


# ================================================================= compliance


def compliance(company, site, month):
    """§6.4: daily and weekly breaches, and the 52-week average. A week that
    straddles two months is evaluated whole."""
    period = ensure_period(company, site, month)
    rules = rules_of(period)
    first, last = month, month_end(month)
    weeks = iso_weeks(first, last)
    wfirst, wlast = weeks[0], weeks[-1] + timedelta(days=6)
    employees = list(site_employees(company, site))
    w = Window(company, site, employees, wfirst, wlast, rules, strict_calendar=False)

    daily, weekly = [], []
    for e in employees:
        for d in w.days:
            if first <= d <= last:
                r = w.record(e, d)
                if r.worked > rules.max_daily_min:
                    x = w.decision(e, d, K.DAILY_LIMIT_EXCEEDED)
                    daily.append({"code": e.code, "nameEn": e.name_en, "date": d.isoformat(), "worked": r.worked,
                                  "limit": rules.max_daily_min, "citation": rules.citations["dailyLimit"],
                                  "acknowledged": bool(x and x.state == ExceptionStateChoices.ACKNOWLEDGED),
                                  "reason": x.resolution if x else None})
        for monday in weeks:
            days = [monday + timedelta(days=i) for i in range(7)]
            total = sum(w.record(e, d).worked for d in days)
            if total > rules.max_weekly_min:
                weekly.append({"code": e.code, "nameEn": e.name_en, "weekStart": monday.isoformat(),
                               "weekEnd": days[-1].isoformat(), "worked": total, "limit": rules.max_weekly_min,
                               "citation": rules.citations["weeklyLimit"]})

    # The proviso: a week may reach 60 hours, the 52-week average may not pass 56.
    annual = []
    afirst = wlast - timedelta(days=52 * 7 - 1)
    yearly = Window(company, site, employees, afirst, wlast, rules, strict_calendar=False)
    for e in employees:
        totals = []
        for i in range(52):
            monday = afirst + timedelta(days=7 * i)
            days = [monday + timedelta(days=j) for j in range(7)]
            if not any(yearly.employed(e, d) for d in days):
                continue
            has_data = any((e.pk, d) in yearly.punches or (e.pk, d) in yearly.adjustments for d in days)
            if not has_data:
                continue
            totals.append(sum(yearly.record(e, d).worked for d in days))
        if totals:
            average = sum(totals) // len(totals)
            if average > rules.annual_average_weekly_min:
                annual.append({"code": e.code, "nameEn": e.name_en, "weeks": len(totals), "average": average,
                               "limit": rules.annual_average_weekly_min, "citation": rules.citations["annual"]})
    return {
        "period": period_out(period), "daily": daily, "weekly": weekly, "annual": annual,
        "count": len(daily) + len(weekly) + len(annual),
        "limits": {"daily": rules.max_daily_min, "weekly": rules.max_weekly_min,
                   "annualAverage": rules.annual_average_weekly_min},
        "rules": {"version": rules.version, "confidence": rules.confidence},
        "note": "Weeks are evaluated whole, including days outside the month. The 52-week average counts the weeks "
                "with attendance on file.",
    }


# ================================================================ adjustments


def _adj_json(a):
    if a is None:
        return None
    return {"newStatus": a.new_status or None, "in": a.in_time_min, "out": a.out_time_min, "removed": a.removed,
            "reason": a.reason}


def _day_period(company, employee, d):
    if d > clock.today():
        raise AttendanceRefused({"date": ["A day that has not happened cannot be adjusted."]})
    if employee.doj and d < employee.doj:
        raise AttendanceRefused({"date": [f"Before the date of joining ({employee.doj.isoformat()})."]})
    period = ensure_period(company, site_of(employee), month_start(d))
    refuse_if_locked(period)
    return period


def _write_adjustment(company, employee, d, period, user, *, reason, **fields):
    with transaction.atomic():
        live = (Adjustment.objects.select_for_update()
                .filter(employee=employee, business_date=d, is_live=True).first())
        if live is not None:
            live.is_live = False
            live.save(update_fields=["is_live", "updated_at"])
        new = Adjustment.objects.create(
            company=company, employee=employee, business_date=d, period=period, reason=reason,
            actor=user, actor_name=actor_name(user), actor_role=actor_role(user, company), **fields,
        )
        if live is not None:
            live.superseded_by = new
            live.save(update_fields=["superseded_by", "updated_at"])
        audit(company, A.ADJUSTMENT_REMOVED if fields.get("removed") else A.ADJUSTED, user, employee=employee,
              day=d, period=period, before=_adj_json(live), after=_adj_json(new), reason=reason)
    return new


def adjust(company, employee, d, *, new_status="", in_time_min=None, out_time_min=None, reason="", note="",
           user=None):
    """§9.2: an overlay, never an edit. Supersedes any live adjustment."""
    period = _day_period(company, employee, d)
    new_status = new_status or ""
    if new_status and new_status not in SETTABLE_STATUSES:
        what = DayStatusChoices(new_status).label if new_status in DayStatusChoices.values else new_status
        raise AttendanceRefused({"newStatus": [
            f"{what} cannot be set by hand: holidays come from the published calendar, and overtime and "
            "exceptions are computed."]})
    if not new_status and in_time_min is None and out_time_min is None:
        raise AttendanceRefused({"newStatus": ["Set a status, or regularise an in- or out-time."]})
    for name, value in (("inTimeMin", in_time_min), ("outTimeMin", out_time_min)):
        if value is not None and not 0 <= value <= 2879:
            raise AttendanceRefused({name: ["A time is minutes from midnight, 0 to 2879 (past midnight is +1440)."]})
    if in_time_min is not None and out_time_min is not None and out_time_min <= in_time_min:
        raise AttendanceRefused({"outTimeMin": ["The out-time must come after the in-time."]})
    reason = _reason(reason, "a reason for the correction")
    return _write_adjustment(company, employee, d, period, user, reason=reason, new_status=new_status,
                             in_time_min=in_time_min, out_time_min=out_time_min, note=(note or "").strip())


def remove_adjustment(company, employee, d, *, reason="", user=None):
    """The day computes again as if there had been no correction (§1.2)."""
    period = _day_period(company, employee, d)
    live = Adjustment.objects.filter(employee=employee, business_date=d, is_live=True).first()
    if live is None or live.removed:
        raise AttendanceRefused({"adjustment": ["This day has no correction to remove."]}, status=409)
    reason = _reason(reason, "a reason for removing the correction")
    return _write_adjustment(company, employee, d, period, user, reason=reason, removed=True)


# ================================================================== decisions

ADJUSTING = {
    K.MISSING_OUT_PUNCH: {"REGULARISE": "out", "HALF_DAY": DayStatusChoices.HALF_DAY},
    K.MISSING_IN_PUNCH: {"REGULARISE": "in", "HALF_DAY": DayStatusChoices.HALF_DAY},
    K.NO_PUNCH_ROSTERED: {"MARK_ABSENT": DayStatusChoices.ABSENT, "MARK_LEAVE": DayStatusChoices.ON_LEAVE,
                          "MARK_ON_DUTY": DayStatusChoices.ON_DUTY},
    K.ABSENT_NO_LEAVE: {"MARK_LWP": DayStatusChoices.LEAVE_WITHOUT_PAY, "MARK_LEAVE": DayStatusChoices.ON_LEAVE},
}
DECIDING = {
    K.LATE_ARRIVAL: {"ACCEPT": ""},
    # Approval is recorded; either way the overtime is payable (s.108).
    K.OT_UNAPPROVED: {"APPROVE": "APPROVED", "REJECT": "REJECTED"},
    K.WORKED_WEEKLY_HOLIDAY: {"CONFIRM": "CONFIRMED"},
    K.WORKED_FESTIVAL_HOLIDAY: {"CONFIRM": "CONFIRMED"},
}


def _open_on(company, employee, d, kind, period):
    w = Window(company, site_of(employee), [employee], d, d, rules_of(period))
    if kind not in w.record(employee, d).exceptions:
        raise AttendanceRefused({"kind": [f"No {EXCEPTIONS[kind][0].lower()} on {d.isoformat()}."]}, status=409)
    return w


def _decide(company, employee, d, kind, period, user, *, state, outcome="", resolution="", rules=None):
    with transaction.atomic():
        live = (ExceptionDecision.objects.select_for_update()
                .filter(employee=employee, business_date=d, kind=kind, is_live=True).first())
        if live is not None:
            live.is_live = False
            live.save(update_fields=["is_live", "updated_at"])
        x = ExceptionDecision.objects.create(
            company=company, employee=employee, business_date=d, period=period, kind=kind, state=state,
            outcome=outcome, resolution=resolution, decided_by=user, decided_by_name=actor_name(user))
        if live is not None:
            live.superseded_by = x
            live.save(update_fields=["superseded_by", "updated_at"])
        if kind in HOLIDAY_WORK and rules is not None:
            _credit(company, employee, d, kind, x, rules)
        audit(company, A.EXCEPTION_ACKNOWLEDGED if state == ExceptionStateChoices.ACKNOWLEDGED else (
            A.HOLIDAY_WORK_CONFIRMED if kind in HOLIDAY_WORK else A.EXCEPTION_RESOLVED), user, employee=employee,
            day=d, period=period, after={"kind": kind, "state": state, "outcome": outcome}, reason=resolution)
    return x


def _credit(company, employee, d, kind, decision, rules):
    """s.103 / s.118: BOTH the compensatory days and, for a festival, the
    substitute holiday -- paying the premium and forgetting the day is the
    most common festival-holiday defect."""
    if kind == K.WORKED_WEEKLY_HOLIDAY:
        rows = [(CreditKindChoices.COMPENSATORY, rules.compensatory_weekly, rules.citations["compensatoryWeekly"])]
    else:
        rows = [(CreditKindChoices.COMPENSATORY, rules.compensatory_festival, rules.citations["compensatory"]),
                (CreditKindChoices.SUBSTITUTE, rules.substitute_festival, rules.citations["compensatory"])]
    from leaveledgerio.services.core import post_credit

    for k, days, cite in rows:
        if days:
            credit = CompensatoryCredit.objects.create(company=company, employee=employee, business_date=d, kind=k,
                                                       days=Decimal(days), decision=decision, citation=cite or "")
            # The leave ledger's CREDIT_EARNED, in the same transaction.
            post_credit(credit)


def resolve(company, employee, d, kind, action, *, reason="", in_time_min=None, out_time_min=None, user=None):
    """§9.3. A daily-limit breach is refused here: it takes /acknowledge only."""
    if kind == K.DAILY_LIMIT_EXCEEDED:
        raise AttendanceRefused({"kind": [
            "A daily-limit breach cannot be resolved away: the hours were worked and are payable. Acknowledge "
            "it with a reason."]}, status=422)
    if kind not in EXCEPTIONS:
        raise AttendanceRefused({"kind": [f"Unknown exception kind {kind!r}."]})
    choices = {**ADJUSTING.get(kind, {}), **DECIDING.get(kind, {})}
    if action not in choices:
        raise AttendanceRefused({"action": [f"{EXCEPTIONS[kind][0]}: action must be one of {', '.join(choices)}."]})
    period = _day_period(company, employee, d)
    w = _open_on(company, employee, d, kind, period)
    if w.decision(employee, d, kind) is not None:
        raise AttendanceRefused({"kind": ["Already decided."]}, status=409)
    if kind in ADJUSTING:
        target = ADJUSTING[kind][action]
        if target == "out":
            if out_time_min is None:
                raise AttendanceRefused({"outTimeMin": ["Give the out-time the day ended at."]})
            return adjust(company, employee, d, out_time_min=out_time_min, reason=reason, user=user)
        if target == "in":
            if in_time_min is None:
                raise AttendanceRefused({"inTimeMin": ["Give the in-time the day started at."]})
            return adjust(company, employee, d, in_time_min=in_time_min, reason=reason, user=user)
        return adjust(company, employee, d, new_status=target, reason=reason, user=user)
    if action == "REJECT":
        reason = _reason(reason, "a reason for rejecting the overtime (it is still paid)")
    return _decide(company, employee, d, kind, period, user, state=ExceptionStateChoices.RESOLVED,
                   outcome=DECIDING[kind][action], resolution=(reason or "").strip(), rules=w.rules)


def acknowledge(company, employee, d, kind, *, reason="", user=None):
    """§5: a statutory breach is acknowledged, never resolved. It stays in
    the compliance report with the reason and who gave it."""
    if kind != K.DAILY_LIMIT_EXCEEDED:
        raise AttendanceRefused({"kind": ["Only a statutory breach is acknowledged; resolve this one."]})
    period = _day_period(company, employee, d)
    w = _open_on(company, employee, d, kind, period)
    if w.decision(employee, d, kind) is not None:
        raise AttendanceRefused({"kind": ["Already acknowledged."]}, status=409)
    reason = _reason(reason, "the reason for the hours")
    return _decide(company, employee, d, kind, period, user, state=ExceptionStateChoices.ACKNOWLEDGED,
                   resolution=reason)


def confirm_holiday_work(company, site, month, *, reason="", user=None):
    """§10.4: confirm every open holiday-working day in the month, crediting
    the compensatory and substitute days."""
    period = ensure_period(company, site, month)
    refuse_if_locked(period)
    rules = rules_of(period)
    employees = list(site_employees(company, site))
    w = Window(company, site, employees, month, month_end(month), rules)
    confirmed = 0
    for e in employees:
        for d in w.days:
            for k in w.open_kinds(e, d):
                if k in HOLIDAY_WORK:
                    _decide(company, e, d, k, period, user, state=ExceptionStateChoices.RESOLVED,
                            outcome="CONFIRMED", resolution=(reason or "").strip(), rules=rules)
                    confirmed += 1
    return {"confirmed": confirmed}


# ============================================================= lock / reopen


def lock(company, site, month, *, user=None, acknowledge_reason=None):
    """§9.4: refuses while a blocking gate is open; on success writes the
    snapshots, locks, and audits.

    Attendance intake §6.1: unresolved exceptions may be locked over with an
    acknowledgement -- a reason, stored on the period with the count, so
    "why was March locked with 7 open exceptions" has an answer. Every other
    gate still blocks."""
    period = ensure_period(company, site, month)
    if period.status == PeriodStatusChoices.LOCKED:
        raise AttendanceRefused({"period": ["Already locked."]}, status=409)
    summary = close_summary(company, site, month)
    acknowledged = 0
    if not summary["canLock"]:
        open_gates = [g for g in summary["gates"] if g["blocks"] and g["count"]]
        others = [g for g in open_gates if g["key"] != "high"]
        high = next((g for g in open_gates if g["key"] == "high"), None)
        if others or acknowledge_reason is None:
            detail = {"gates": summary["gates"]}
            if high and not others:
                detail.update(needsAcknowledgement=True, count=high["count"])
            raise AttendanceRefused({"period": [f"Cannot lock: {'; '.join(g['label'] for g in open_gates)}."]},
                                    status=422, detail=detail)
        acknowledge_reason = _reason(acknowledge_reason, "the reason for locking over open exceptions")
        acknowledged = high["count"]
    rules = rules_of(period)
    employees = list(site_employees(company, site))
    w = Window(company, site, employees, month, month_end(month), rules)
    with transaction.atomic():
        for e in employees:
            for d in w.days:
                r = w.record(e, d)
                if r.status is None:
                    continue
                shift = shift_on(w.assignments.get(e.pk), d)
                DaySnapshot.objects.update_or_create(
                    employee=e, business_date=d,
                    defaults={"company": company, "period": period, "status": r.status, "worked_minutes": r.worked,
                              "overtime_minutes": r.overtime, "late_minutes": r.late,
                              "shift_id": shift.id if shift else None, "rule_set_id": rules.rule_set_id,
                              "input_hash": w.input_hash(e, d), "stale": False})
        period.status = PeriodStatusChoices.LOCKED
        period.locked_at = timezone.now()
        period.locked_by = user
        period.acknowledge_reason = acknowledge_reason or ""
        period.exceptions_acknowledged = acknowledged
        period.save(update_fields=["status", "locked_at", "locked_by", "acknowledge_reason",
                                   "exceptions_acknowledged", "updated_at"])
        audit(company, A.PERIOD_LOCKED, user, period=period, reason=acknowledge_reason or "",
              after={"month": month.isoformat(), "exceptionsAcknowledged": acknowledged})
    return period


def reopen(company, site, month, *, reason="", user=None, confirmed_invalidates_payroll=False):
    """§9.5: needs a reason, and the reopen permission (not the lock one).
    The snapshots go stale so payroll reassesses anything it computed.

    Attendance intake §6.2, three gates in order: a reason; then, when a
    payroll run consumed the month, an explicit confirmation -- and the run
    it invalidates is stored on the period."""
    period = ensure_period(company, site, month)
    if period.status != PeriodStatusChoices.LOCKED:
        raise AttendanceRefused({"period": ["Only a locked period is reopened."]}, status=409)
    reason = _reason(reason, "the reason for reopening")
    run = period.payroll_run_ref
    if run and not confirmed_invalidates_payroll:
        when = period.payroll_processed_on.isoformat() if period.payroll_processed_on else "an earlier date"
        raise AttendanceRefused(
            {"period": [f"Payroll for {period.period_month:%B %Y} was processed on {when}. Unlocking marks that "
                        "run invalid and it must be re-run."]}, status=409,
            detail={"needsConfirmation": True, "impact": {"runRef": run, "processedOn": when,
                                                          "label": f"{period.period_month:%B %Y}"}})
    with transaction.atomic():
        period.status = PeriodStatusChoices.OPEN
        period.stage = "OPEN"
        period.reopened_at = timezone.now()
        period.reopened_by = user
        period.reopen_reason = reason
        if run:
            period.payroll_invalidated_ref, period.payroll_run_ref = run, ""
        period.save(update_fields=["status", "stage", "reopened_at", "reopened_by", "reopen_reason",
                                   "payroll_invalidated_ref", "payroll_run_ref", "updated_at"])
        DaySnapshot.objects.filter(period=period).update(stale=True)
        audit(company, A.PERIOD_REOPENED, user, period=period, reason=reason,
              after={"payrollInvalidated": run or None})
    return period


def recompute(company, site, month, *, user=None):
    """§9.6: recompute the month without locking it. Reads punches and
    adjustments and writes nothing but the cache: on a locked period, a
    snapshot whose inputs have moved is marked stale."""
    period = ensure_period(company, site, month)
    rules = rules_of(period)
    employees = list(site_employees(company, site))
    w = Window(company, site, employees, month, month_end(month), rules)
    days = exceptions = stale = 0
    snapshots = {(s.employee_id, s.business_date): s for s in DaySnapshot.objects.filter(period=period)}
    for e in employees:
        for d in w.days:
            r = w.record(e, d)
            if r.status is None:
                continue
            days += 1
            exceptions += len(w.open_kinds(e, d))
            snap = snapshots.get((e.pk, d))
            if snap is not None and not snap.stale and snap.input_hash != w.input_hash(e, d):
                stale += 1
                snap.stale = True
                snap.save(update_fields=["stale", "updated_at"])
    audit(company, A.RECOMPUTED, user, period=period, after={"days": days, "openExceptions": exceptions,
                                                            "staleSnapshots": stale})
    return {"days": days, "employees": len(employees), "openExceptions": exceptions, "staleSnapshots": stale,
            "computedAt": timezone.now().isoformat()}


# ===================================================================== import


def _parse_instant(text):
    """'2026-10-14 08:02' (Dhaka time) or an ISO instant with an offset."""
    text = str(text or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            value = datetime.strptime(text.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        return value if value.tzinfo else value.replace(tzinfo=DHAKA)
    return None


def import_punches(company, site, rows, *, user=None):
    """Punches from a file (source IMPORT). Idempotent: each row carries a key
    from its own content, so importing the same file twice adds nothing. A
    row that cannot be placed is quarantined with the reason, never dropped
    (§8.2, §8.3)."""
    by_code = {e.code: e for e in site_employees(company, site)}
    today = clock.today()
    inserted, duplicates, quarantined = 0, 0, []

    def hold(row, reason, detail):
        PunchQuarantine.objects.create(company=company, site=site, device_id="IMPORT", raw_payload=row,
                                       reason=reason, detail=detail)
        quarantined.append({"row": row, "reason": reason, "detail": detail})

    for row in rows:
        code = str(row.get("employeeCode") or "").strip().upper()
        direction = str(row.get("direction") or "").strip().upper()
        at = _parse_instant(row.get("punchedAt"))
        if not code or direction not in ("IN", "OUT") or at is None:
            hold(row, QuarantineReasonChoices.MALFORMED, "Needs employeeCode, punchedAt (YYYY-MM-DD HH:MM) and "
                                                         "direction IN or OUT.")
            continue
        employee = by_code.get(code)
        if employee is None:
            hold(row, QuarantineReasonChoices.UNKNOWN_EMPLOYEE, f"No employee {code} at {site.name}.")
            continue
        local_day = at.astimezone(DHAKA).date()
        if local_day > today:
            hold(row, QuarantineReasonChoices.FUTURE_DATED, "In the future.")
            continue
        windows = assignments_by_employee([employee], local_day - timedelta(days=1), local_day).get(employee.pk)
        business_date, _ = business_date_and_minute(at, windows)
        if shift_on(windows, business_date) is None:
            hold(row, QuarantineReasonChoices.NO_SHIFT, f"{code} has no shift on {business_date.isoformat()}.")
            continue
        period = ensure_period(company, site, month_start(business_date))
        if period.status == PeriodStatusChoices.LOCKED:
            hold(row, QuarantineReasonChoices.PERIOD_LOCKED, f"{business_date:%B %Y} is locked.")
            continue
        key = hashlib.sha1(f"{code}|{at.astimezone(DHAKA).isoformat()}|{direction}".encode()).hexdigest()[:40]
        if Punch.objects.filter(device_id="IMPORT", device_punch_id=key).exists():
            duplicates += 1
            continue
        try:
            with transaction.atomic():
                Punch.objects.create(company=company, employee=employee, site=site, punched_at=at,
                                     business_date=business_date, direction=direction,
                                     source=PunchSourceChoices.IMPORT, device_id="IMPORT", device_punch_id=key,
                                     raw_payload=row, ingested_by=user)
            inserted += 1
        except IntegrityError:
            duplicates += 1
    audit(company, A.PUNCH_INGESTED, user, after={"inserted": inserted, "duplicates": duplicates,
                                                  "quarantined": len(quarantined)})
    return {"inserted": inserted, "duplicates": duplicates, "quarantined": quarantined}


# ===================================================================== shifts


def shift_out(s):
    return {
        "uid": str(s.uid), "code": s.code, "label": s.label, "labelBn": s.label_bn or None,
        "start": hhmm(s.start_min), "end": hhmm(s.end_min), "startMin": s.start_min, "endMin": s.end_min,
        "standardMinutes": s.standard_minutes, "unpaidBreak": s.unpaid_break_minutes,
        "grace": s.late_grace_minutes, "otStartsAfter": s.ot_starts_after_min,
        "requiresPreApproval": s.requires_pre_approval, "isNightShift": s.is_night_shift,
        "effectiveFrom": s.effective_from.isoformat(),
        "assigned": ShiftAssignment.objects.filter(shift=s).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=clock.today())).count(),
    }


def create_shift(company, site, data, *, user=None):
    try:
        start, end = int(data["startMin"]), int(data["endMin"])
    except (KeyError, TypeError, ValueError):
        raise AttendanceRefused({"startMin": ["Give the start and end as minutes from midnight."]}) from None
    if end <= start:
        end += 1440  # an end before the start crosses midnight
    code = str(data.get("code") or "").strip().upper()
    label = str(data.get("label") or "").strip()
    if not code or not label:
        raise AttendanceRefused({"code": ["A shift needs a code and a label."]})
    brk = int(data.get("unpaidBreak", 60))
    standard = int(data.get("standardMinutes") or (end - start - brk))
    if standard > end - start - brk + 1:
        raise AttendanceRefused({"standardMinutes": [
            f"The standard day ({standard} min) cannot exceed the span less the break ({end - start - brk} min)."]})
    try:
        effective_from = date.fromisoformat(data.get("effectiveFrom") or clock.today().isoformat())
        with transaction.atomic():
            shift = Shift.objects.create(
                company=company, site=site, code=code, label=label, label_bn=data.get("labelBn") or "",
                start_min=start, end_min=end, standard_minutes=standard, unpaid_break_minutes=brk,
                late_grace_minutes=int(data.get("grace", 10)), ot_starts_after_min=int(data.get("otStartsAfter", 0)),
                requires_pre_approval=bool(data.get("requiresPreApproval", True)), is_night_shift=end > 1439,
                effective_from=effective_from, created_by=user)
    except IntegrityError:
        raise AttendanceRefused({"code": [f"A shift {code} already starts on that date at this site."]},
                                status=409) from None
    except ValueError:
        raise AttendanceRefused({"effectiveFrom": ["effectiveFrom must be a date, YYYY-MM-DD."]}) from None
    return shift


def assign_shift(company, shift, employees, effective_from, *, user=None):
    """Effective-dated and never overlapping (§3.2): the assignment in force
    closes the day before; one starting later is refused, not overwritten."""
    if effective_from in [None, ""]:
        effective_from = clock.today()
    if shift.effective_from > effective_from:
        raise AttendanceRefused({"effectiveFrom": [f"Shift {shift.code} starts on {shift.effective_from}."]})
    done = []
    for e in employees:
        if locked_months(site_of(e), effective_from, effective_from):
            raise AttendanceRefused({"effectiveFrom": [
                f"{effective_from:%B %Y} is locked for {e.code}'s site; assign from an open month."]}, status=409)
        with transaction.atomic():
            later = ShiftAssignment.objects.filter(employee=e, effective_from__gte=effective_from)
            if later.exists():
                raise AttendanceRefused({"effectiveFrom": [
                    f"{e.code} already has a shift assignment from {later.first().effective_from}."]}, status=409)
            cover = (ShiftAssignment.objects.select_for_update().filter(employee=e, effective_from__lt=effective_from)
                     .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from)).first())
            if cover is not None:
                cover.effective_to = effective_from - timedelta(days=1)
                cover.save(update_fields=["effective_to", "updated_at"])
            ShiftAssignment.objects.create(company=company, employee=e, shift=shift, effective_from=effective_from,
                                           assigned_by=user)
            audit(company, A.SHIFT_ASSIGNED, user, employee=e, day=effective_from,
                  after={"shift": shift.code, "from": effective_from.isoformat()})
        done.append(e.code)
    return done


def profile_shift_date(employee, shift):
    """When a shift set on the employee profile takes effect: today for a
    change; for a first shift, the date of joining -- so the days already
    worked are not left without one -- moved past any locked month and no
    earlier than the shift itself."""
    today = clock.today()
    if ShiftAssignment.objects.filter(employee=employee).exists():
        return today
    start = max(min(employee.doj or today, today), shift.effective_from)
    locked = locked_months(site_of(employee), start, today)
    if locked:
        start = max(start, month_end(max(locked)) + timedelta(days=1))
    return min(start, today)


def set_profile_shift(company, employee, shift, *, user=None):
    """The employee profile's Shift field (§3.2): an assignment from
    `profile_shift_date`, never an edit of one in force. Returns
    (effective_from, previous shift) or None when nothing changed."""
    today = clock.today()
    current = current_assignment(employee, today)
    if current is not None and current.shift_id == shift.pk:
        return None
    if shift.site_id != site_of(employee).pk:
        raise AttendanceRefused({"shift": [f"Shift {shift.code} belongs to another site."]})
    effective = profile_shift_date(employee, shift)
    if current is not None and current.effective_from == effective:
        # Changed again the same day: the assignment that started today is replaced.
        if locked_months(site_of(employee), effective, effective):
            raise AttendanceRefused({"shift": [f"{effective:%B %Y} is locked."]}, status=409)
        previous = current.shift
        current.shift = shift
        current.assigned_by = user
        current.save(update_fields=["shift", "assigned_by", "updated_at"])
        audit(company, A.SHIFT_ASSIGNED, user, employee=employee, day=effective,
              before={"shift": previous.code}, after={"shift": shift.code, "from": effective.isoformat()})
        return effective, previous
    assign_shift(company, shift, [employee], effective, user=user)
    return effective, current.shift if current else None


# =================================================================== calendar


def calendar_out(site, year):
    cal = HolidayCalendar.objects.filter(site=site, calendar_year=year).prefetch_related("days").first()
    if cal is None:
        return {"year": year, "status": None, "weeklyPattern": {}, "days": [], "consultedWith": "",
                "publishedAt": None, "lockedMonths": []}
    return {
        "year": year, "status": cal.status, "weeklyPattern": cal.weekly_pattern,
        "days": [{"date": d.holiday_date.isoformat(), "name": d.name, "nameBn": d.name_bn or None, "kind": d.kind}
                 for d in cal.days.all()],
        "consultedWith": cal.consulted_with, "publishedAt": cal.published_at.isoformat() if cal.published_at else None,
        "publishedBy": actor_name(cal.published_by) or None,
        "lockedMonths": [m.strftime("%Y-%m") for m in locked_months(site, date(year, 1, 1), date(year, 12, 31))],
    }


def save_calendar(company, site, year, *, weekly_pattern, days, consulted_with="", user=None):
    if locked_months(site, date(year, 1, 1), date(year, 12, 31)):
        raise AttendanceRefused({"calendar": [
            f"A month of {year} is locked at {site.name}; the calendar it was computed on cannot change."]},
            status=409)
    pattern = {}
    for k, v in (weekly_pattern or {}).items():
        if str(k) not in {str(i) for i in range(1, 8)} or float(v) not in (0.5, 1):
            raise AttendanceRefused({"weeklyPattern": [
                "Key by ISO weekday (1 Monday … 7 Sunday); 1 is a full weekly holiday, 0.5 a half day."]})
        pattern[str(k)] = 1 if float(v) == 1 else 0.5
    cleaned = []
    for d in days or []:
        try:
            when = date.fromisoformat(d["date"])
        except (KeyError, TypeError, ValueError):
            raise AttendanceRefused({"days": ["Each day needs a date, YYYY-MM-DD."]}) from None
        if when.year != year:
            raise AttendanceRefused({"days": [f"{when} is not in {year}."]})
        if not str(d.get("name") or "").strip():
            raise AttendanceRefused({"days": [f"{when} needs a name."]})
        if d.get("kind") not in ("FESTIVAL_HOLIDAY", "PUBLIC_HOLIDAY", "HALF_DAY"):
            raise AttendanceRefused({"days": [f"{when}: kind must be FESTIVAL_HOLIDAY, PUBLIC_HOLIDAY or HALF_DAY."]})
        cleaned.append((when, d["name"].strip(), (d.get("nameBn") or "").strip(), d["kind"]))
    if len({c[0] for c in cleaned}) != len(cleaned):
        raise AttendanceRefused({"days": ["A date is listed twice."]})
    with transaction.atomic():
        cal, _ = HolidayCalendar.objects.get_or_create(company=company, site=site, calendar_year=year)
        cal.weekly_pattern = pattern
        cal.consulted_with = (consulted_with or "").strip()
        cal.save(update_fields=["weekly_pattern", "consulted_with", "updated_at"])
        cal.days.all().delete()
        HolidayCalendarDay.objects.bulk_create([
            HolidayCalendarDay(calendar=cal, holiday_date=w, name=n, name_bn=bn, kind=k) for w, n, bn, k in cleaned])
    return cal


def publish_calendar(company, site, year, *, user=None):
    cal = HolidayCalendar.objects.filter(site=site, calendar_year=year).first()
    if cal is None:
        raise AttendanceRefused({"calendar": [f"Save the {year} calendar before publishing it."]}, status=409)
    if not any(float(v) >= 1 for v in (cal.weekly_pattern or {}).values()):
        raise AttendanceRefused({"weeklyPattern": [
            "A worker is entitled to a weekly holiday (s.103): mark at least one full day."]})
    cal.status = CalendarStatusChoices.PUBLISHED
    cal.published_at = timezone.now()
    cal.published_by = user
    cal.save(update_fields=["status", "published_at", "published_by", "updated_at"])
    audit(company, A.CALENDAR_PUBLISHED, user, after={"site": site.name, "year": year,
                                                      "weeklyPattern": cal.weekly_pattern,
                                                      "days": cal.days.count()})
    return cal


__all__ = [
    "AttendanceRefused", "acknowledge", "adjust", "assign_shift", "calendar_out", "close_summary", "compliance",
    "confirm_holiday_work", "create_shift", "day_detail", "elections_of", "exceptions_list", "grid",
    "import_punches", "lock", "publish_calendar", "recompute", "remove_adjustment", "reopen", "resolve",
    "save_calendar", "set_profile_shift", "shift_out",
]
