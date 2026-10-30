"""What the run payroll screen reads: the schedule overview (stage 1), a run
with its lines and exceptions (stages 2-5), the funding split (§10.2) and
the wage register (§10.1)."""

from collections import defaultdict

from common import clock
from common.money import ZERO, money_str, to_decimal

from ..choices import FIXED, RunStateChoices
from ..models import PayrollRun
from . import bankfiles

S = RunStateChoices


def _iso(d):
    return d.isoformat() if d else None


def _person(e):
    return {"uid": str(e.uid), "code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn or None,
            "designation": e.designation.title if getattr(e, "designation_id", None) and e.designation else None}


# ================================================================ overview


def overview(company, period_start):
    """One card per site: the schedule that governs it, who is on it, the
    estimated gross, the s.123 due date and where its run stands."""
    from employeeio.services.salary import structure_in_force
    from employeeio.services.sites import sites_of
    from paysetio.services.calendar import CalendarMissing, Calendar, month_bounds, payment_date, statutory_deadline
    from paysetio.services.ops import readiness, schedule_in_force, schedule_out
    from timekeepingio.models import AttendancePeriod

    from .inputs import team

    _, period_end = month_bounds(period_start)
    today = clock.today()
    cards = []
    for site in sites_of(company):
        sched = schedule_in_force(company, site, period_end)
        run = (PayrollRun.objects.filter(site=site, period_start=period_start, run_type="REGULAR")
               .exclude(state=S.CANCELLED).first())
        stub = PayrollRun(company=company, site=site, period_start=period_start, period_end=period_end)
        members = list(team(stub))
        est, no_structure = ZERO, 0
        for e in members:
            st = structure_in_force(e, period_end)
            if st is None:
                no_structure += 1
            else:
                est += st.gross
        try:
            due = statutory_deadline(Calendar(site), period_end)
        except CalendarMissing:
            due = None
        att = AttendancePeriod.objects.filter(site=site, period_month=period_start).first()
        ready = readiness(company, site, period_start)
        cards.append({
            "site": {"uid": str(site.uid), "code": site.code, "name": site.name, "isDefault": site.is_default},
            "schedule": schedule_out(sched, site=site),
            "scheduleScope": None if sched is None else ("SITE" if sched.site_id else "COMPANY"),
            "supported": sched is not None and sched.frequency == "MONTHLY",
            "headcount": len(members), "estimatedGross": money_str(est), "withoutStructure": no_structure,
            "cutoffDate": _iso(period_start.replace(day=min(sched.cutoff_day, period_end.day)))
            if sched is not None and sched.cutoff_day else None,
            "periodEnd": period_end.isoformat(),
            "dueDate": _iso(due), "daysToDue": (due - today).days if due else None,
            "paymentDate": _iso(payment_date(period_start, sched.payment_day))
            if sched is not None and sched.payment_day else None,
            "attendance": {"locked": bool(att and att.status == "LOCKED"),
                           "stage": att.stage if att else "OPEN", "lockedAt": _iso(att.locked_at) if att else None},
            "readiness": ready,
            "run": run_head(run) if run else None,
        })
    return {"period": period_start.strftime("%Y-%m"), "periodEnd": period_end.isoformat(), "today": today.isoformat(),
            "sites": cards}


def run_head(run):
    return {"uid": str(run.uid), "ref": run.ref, "state": run.state, "stateLabel": S(run.state).label,
            "period": run.period, "runType": run.run_type, "createdBy": run.created_by_name or None,
            "approvedBy": run.approved_by_name or None, "approvedAt": _iso(run.approved_at),
            "closedAt": _iso(run.closed_at), "includedCount": run.included_count, "memberCount": run.member_count,
            "totalNet": money_str(run.total_net), "totalTax": money_str(run.total_tax)}


# ===================================================================== run


def line_out(ln):
    e = ln.employee
    return {
        "uid": str(ln.uid), "employee": _person(e), "included": ln.included,
        "exclusionReason": ln.exclusion_reason, "excludedBy": ln.excluded_by_name or None,
        "structure": str(ln.structure.uid) if ln.structure_id else None,
        "grossBeforeProration": money_str(ln.gross_before_proration) if ln.gross_before_proration is not None else None,
        "calendarDays": ln.calendar_days, "payableDays": format(ln.payable_days.normalize(), "f"),
        "daysLost": format(ln.days_lost.normalize(), "f"), "lwpDays": format(ln.lwp_days.normalize(), "f"),
        "joinDate": _iso(ln.join_date_in_period), "leaveDate": _iso(ln.leave_date_in_period),
        "prorationFactor": format(ln.proration_factor.normalize(), "f"),
        "otHours": format(ln.ot_hours, "f"), "otHoursAttendance": format(ln.ot_hours_attendance, "f"),
        "otSource": ln.ot_hours_source, "otReason": ln.ot_override_reason or None,
        "otAmount": money_str(ln.ot_amount), "otBase": money_str(ln.ot_base_amount),
        "gross": money_str(ln.gross), "tax": money_str(ln.tax_withheld), "pfEmployee": money_str(ln.pf_employee),
        "pfEmployer": money_str(ln.pf_employer), "otherDeductions": money_str(ln.other_deductions),
        "net": money_str(ln.net_pay), "blocked": ln.blocked, "computed": ln.computed_at is not None,
        "method": ln.payment_method, "provider": ln.mfs_provider or None, "destination": ln.destination_ref or None,
        "paymentStatus": ln.payment_status, "paidAt": _iso(ln.paid_at),
        "earnings": ln.earnings_json or [], "deductions": ln.deductions_json or [],
        "taxDerivation": ln.tax_derivation_json, "inputHash": ln.input_hash or None,
    }


def exception_out(x):
    return {"uid": str(x.uid), "line": str(x.line.uid) if x.line_id else None,
            "employee": _person(x.employee) if x.employee_id else None, "severity": x.severity, "code": x.code,
            "message": x.message, "citation": x.citation or None, "resolved": x.resolved, "resolution": x.resolution,
            "resolutionReason": x.resolution_reason or None, "resolvedBy": x.resolved_by_name or None,
            "resolvedAt": _iso(x.resolved_at)}


def funding(run):
    """§10.2: what the approver is agreeing to fund, by destination."""
    rows = defaultdict(lambda: {"count": 0, "amount": ZERO})
    for method, net in run.lines.filter(included=True).values_list("payment_method", "net_pay"):
        rows[method]["count"] += 1
        rows[method]["amount"] += to_decimal(net)
    return [{"method": m, "count": rows[m]["count"], "amount": money_str(rows[m]["amount"])}
            for m in ("BANK_TRANSFER", "MOBILE_WALLET", "CASH", "CHEQUE") if rows[m]["count"]]


def instruction_out(ins):
    return {"uid": str(ins.uid), "profile": ins.bank_profile_code, "fileName": ins.file_name, "hash": ins.file_hash,
            "rows": ins.row_count, "total": money_str(ins.total_amount), "generatedBy": ins.generated_by_name or None,
            "generatedAt": _iso(ins.generated_at), "encoding": ins.encoding}


def transition_out(t):
    return {"from": t.from_state, "to": t.to_state, "by": t.actor_name or None, "role": t.actor_role,
            "reason": t.reason or None, "at": _iso(t.at)}


def run_out(run, *, me=None):
    from .ops import blocking, corporate_account

    lines = list(run.lines.select_related("employee", "employee__designation", "structure").order_by("employee__code"))
    exceptions = list(run.exceptions.select_related("employee", "line").order_by("id"))
    blockers = blocking(run).count()
    employer_cost = to_decimal(run.total_gross) + to_decimal(run.total_pf_employer)
    profiles = [bankfiles.profile_out(p, corporate_account(run.company, p["code"])) for p in bankfiles.PROFILES]
    for p in profiles:
        src = bankfiles.BY_CODE[p["code"]]
        p["pending"] = sum(1 for ln in lines if ln.included and ln.payment_status in ("PENDING", "FAILED")
                           and bankfiles.matches(src, ln) and ln.net_pay > 0)
    return {
        **run_head(run),
        "site": {"uid": str(run.site.uid), "code": run.site.code, "name": run.site.name},
        "periodStart": run.period_start.isoformat(), "periodEnd": run.period_end.isoformat(),
        "dueDate": run.statutory_due_date.isoformat(), "paymentDate": run.payment_date.isoformat(),
        "daysToDue": (run.statutory_due_date - clock.today()).days,
        "ruleSet": run.rule_set.version, "taxCard": run.tax_card.version, "engineVersion": run.engine_version,
        "elections": run.elections_snapshot, "createdById": str(run.created_by.uid) if run.created_by_id else None,
        "isCreator": bool(me and run.created_by_id == me.pk), "fixed": run.state in FIXED,
        "computedAt": _iso(run.computed_at), "releasedAt": _iso(run.released_at),
        "cancelledReason": run.cancelled_reason,
        "totals": {"gross": money_str(run.total_gross), "tax": money_str(run.total_tax),
                   "pfEmployee": money_str(run.total_pf_employee), "pfEmployer": money_str(run.total_pf_employer),
                   "net": money_str(run.total_net), "employerCost": money_str(employer_cost),
                   "excludedCount": run.excluded_count},
        "blockers": blockers,
        "lines": [line_out(ln) for ln in lines],
        "exceptions": [exception_out(x) for x in exceptions],
        "funding": funding(run),
        "profiles": profiles,
        "instructions": [instruction_out(i) for i in run.instructions.order_by("generated_at")],
        "transitions": [transition_out(t) for t in run.transitions.order_by("at", "id")],
    }


def register(run):
    """§10.1, the s.123 wage register: included lines, by code."""
    rows = []
    for ln in (run.lines.filter(included=True).select_related("employee").order_by("employee__code")):
        e = ln.employee
        rows.append({"code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn or None,
                     "payableDays": format(ln.payable_days.normalize(), "f"), "otHours": format(ln.ot_hours, "f"),
                     "gross": money_str(ln.gross), "tax": money_str(ln.tax_withheld),
                     "pfEmployee": money_str(ln.pf_employee), "otherDeductions": money_str(ln.other_deductions),
                     "net": money_str(ln.net_pay), "method": ln.payment_method, "destination": ln.destination_ref})
    return rows

