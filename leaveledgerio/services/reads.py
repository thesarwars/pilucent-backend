"""What the console reads (frontend spec §6-§10): balances, applications,
the approval queue with its clash block, who is away, an employee's ledger,
encashments, maternity cases and the policy in force.

Every figure here comes from `Positions` / `position()`: no screen computes
what can be spent on its own.
"""

from datetime import date, timedelta

from django.db.models import Q, Sum

from common import clock
from common.money import money_str
from employeeio.models import Employee

from ..choices import LedgerReasonChoices as R
from ..choices import RequestStatusChoices as S
from ..models import Encashment, LeaveHold, LeaveRequest, LedgerEntry, MaternityCase
from .core import (
    GRID,
    ZERO,
    Book,
    Positions,
    days_str,
    ensure_types,
    fmt,
    position,
    position_sentence,
    refresh_credits,
)

FILTERS = ("ALL", "CLAIMED", "NOTHING", "OVERDRAWN")


def roster(company):
    return (Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
            .select_related("department", "designation").order_by("code"))


def employee_out(e):
    return {"code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn or None,
            "department": e.department.title if e.department else None,
            "designation": e.designation.title if e.designation else None,
            "classification": e.classification or None, "establishment": e.establishment or None,
            "gender": e.gender or None, "doj": e.doj.isoformat() if e.doj else None}


def type_out(t, rules=None):
    out = {"code": t.code, "name": t.name, "nameBn": t.name_bn or None, "statutory": t.is_statutory,
           "basis": t.statutory_basis or None, "cycleKind": t.cycle_kind, "accrualKind": t.accrual_kind,
           "halfDayAllowed": t.half_day_allowed, "countsCalendarDays": t.counts_calendar_days,
           "consumesHolidays": t.consumes_public_holidays, "advanceAllowed": t.advance_allowed,
           "encashable": t.encashment_allowed, "onGrid": t.on_grid, "womenOnly": t.gender_restriction == "WOMAN",
           "workersOnly": t.worker_restriction == "WORKER_ONLY", "backdateWindowDays": t.backdate_window_days,
           "requiresMedicalCert": t.requires_medical_cert}
    if rules is not None:
        from .core import fixed_entitlement

        if t.accrual_kind == "FIXED_ANNUAL":
            out["entitlement"] = days_str(fixed_entitlement(t, rules)[0])
    return out


# =================================================================== balances


def balances(company, *, q="", flt="ALL", as_of=None):
    """§6. Every employee across the grid's types, three figures each."""
    as_of = as_of or clock.today()
    types = ensure_types(company)
    grid = [types[c] for c in GRID]
    everyone = list(roster(company))
    refresh_credits(company, as_of, everyone)
    book = Book()
    pos = Positions(company, everyone, grid + [types["COMPENSATORY"]], as_of, book)
    rows = []
    for e in everyone:
        cells = {t.code: pos.of(e, t) for t in grid + [types["COMPENSATORY"]]}
        live = [p for p in cells.values() if p.eligible]
        rows.append({
            **employee_out(e),
            "positions": {code: p.out() for code, p in cells.items()},
            "_claimed": any(p.held or p.committed for p in live),
            "_nothing": any(cells[c].eligible and cells[c].cycle is not None and cells[c].spendable <= 0
                            for c in GRID),
            "_overdrawn": any(p.balance < 0 or p.spendable < 0 for p in live),
        })
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in r["code"].lower() or needle in r["nameEn"].lower()
                or needle in (r["nameBn"] or "") or needle in (r["department"] or "").lower()]
    counts = {"ALL": len(rows), "CLAIMED": sum(r["_claimed"] for r in rows),
              "NOTHING": sum(r["_nothing"] for r in rows), "OVERDRAWN": sum(r["_overdrawn"] for r in rows)}
    key = {"CLAIMED": "_claimed", "NOTHING": "_nothing", "OVERDRAWN": "_overdrawn"}.get(flt)
    if key:
        rows = [r for r in rows if r[key]]
    for r in rows:
        for k in ("_claimed", "_nothing", "_overdrawn"):
            r.pop(k)
    return {"asOf": as_of.isoformat(), "types": [type_out(t) for t in grid], "rows": rows, "counts": counts,
            "rules": {"version": book.rules(as_of).version, "confidence": book.rules(as_of).confidence}}


def summary(company):
    """The header's four figures and the tab counts."""
    today = clock.today()
    year_start = date(today.year, 1, 1)
    granted = (LedgerEntry.objects.filter(company=company, reversed_by__isnull=True, days__gt=0,
                                          effective_date__gte=year_start, effective_date__lte=today,
                                          reason__in=[R.ACCRUAL, R.ADJUSTMENT, R.CREDIT_EARNED])
               .aggregate(s=Sum("days"))["s"] or ZERO)
    held = LeaveHold.objects.filter(company=company, released_at__isnull=True).aggregate(s=Sum("days"))["s"] or ZERO
    waiting = LeaveRequest.objects.filter(company=company, status=S.SUBMITTED).count()
    return {
        "roster": roster(company).count(), "awaiting": waiting, "held": days_str(held),
        "grantedThisYear": days_str(granted),
        "counts": {
            "applications": LeaveRequest.objects.filter(company=company).count(),
            "approvals": waiting,
            "encashment": Encashment.objects.filter(company=company, status__in=["SUBMITTED", "APPROVED"]).count(),
        },
    }


# =============================================================== applications


def phase(req, today):
    """IN_PROGRESS and TAKEN are an approved request read against today."""
    if req.status != S.APPROVED:
        return req.status
    if req.to_date < today:
        return "TAKEN"
    if req.from_date <= today:
        return "IN_PROGRESS"
    return "APPROVED"


def request_out(req, today=None):
    today = today or clock.today()
    return {
        "reference": req.reference, "employee": employee_out(req.employee), "type": req.leave_type.code,
        "typeName": req.leave_type.name, "from": req.from_date.isoformat(), "to": req.to_date.isoformat(),
        "startHalf": req.start_half, "endHalf": req.end_half, "days": days_str(req.days_consumed),
        "breakdown": req.day_breakdown, "status": req.status, "phase": phase(req, today),
        "note": req.note or None, "contact": req.contact_during_leave or None,
        "cover": {"code": req.cover_employee.code, "nameEn": req.cover_employee.name_en} if req.cover_employee else None,
        "evidence": req.evidence or None, "backdated": req.is_backdated, "advance": req.is_advance,
        "nonRefusable": req.non_refusable, "enteredBy": req.created_by_name or None, "onBehalf": req.on_behalf,
        "enteredAt": req.created_at.isoformat(), "decidedBy": req.decided_by_name or None,
        "decidedAt": req.decided_at.isoformat() if req.decided_at else None,
        "declineReason": req.decline_reason or None,
        "entry": req.ledger_entry.reference if req.ledger_entry_id else None,
    }


def applications(company, *, status="ALL", q="", code=""):
    today = clock.today()
    qs = (LeaveRequest.objects.filter(company=company)
          .select_related("employee__department", "employee__designation", "leave_type", "cover_employee",
                          "ledger_entry").order_by("-created_at"))
    if code:
        qs = qs.filter(leave_type__code=code.upper())
    if q:
        qs = qs.filter(Q(employee__code__icontains=q) | Q(employee__name_en__icontains=q) | Q(reference__icontains=q))
    rows = [request_out(r, today) for r in qs[:500]]
    counts = {}
    for r in rows:
        counts[r["phase"]] = counts.get(r["phase"], 0) + 1
    if status != "ALL":
        rows = [r for r in rows if r["phase"] == status or r["status"] == status]
    return {"rows": rows, "counts": {"ALL": sum(counts.values()), **counts}}


# ================================================================ who is away


def who_is_away(company, first, last, employee_ids=None, exclude=None):
    """§5.5. Absences overlapping [first, last], approved and waiting both,
    kept distinct. One lookup behind the calendar and the clash warning, so
    the roster an approver is shown and the clash they are warned about can
    never disagree."""
    qs = (LeaveRequest.objects.filter(company=company, status__in=[S.SUBMITTED, S.APPROVED], from_date__lte=last,
                                      to_date__gte=first)
          .select_related("employee__department", "leave_type").order_by("from_date"))
    if employee_ids is not None:
        qs = qs.filter(employee_id__in=employee_ids)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return list(qs)


def clashes_for(req, peers_qs=None):
    """Peers are the department when the roster carries one, else the site:
    a site-wide clash list on a 300-person roster is noise. Severity is a
    fraction -- two of four is a staffing problem, two of two hundred is not."""
    from employeeio.services.sites import site_of
    from timekeepingio.services.base import site_employees

    e = req.employee
    if e.department_id:
        peers = roster(req.company).filter(department_id=e.department_id).exclude(pk=e.pk)
        scope = e.department.title
    else:
        site = site_of(e)
        peers = site_employees(req.company, site).exclude(pk=e.pk)
        scope = site.name
    peer_ids = list(peers.values_list("pk", flat=True))
    away = who_is_away(req.company, req.from_date, req.to_date, peer_ids, exclude=req)
    people = {a.employee_id for a in away}
    severe = len(peer_ids) > 0 and len(people) / (len(peer_ids) + 1) >= 0.34
    return {
        "scope": scope, "peers": len(peer_ids), "overlapping": len(people), "severe": severe,
        "title": f"{len(people)} also out" if people else "Nobody else out",
        "note": (f"{len(people)} of {len(peer_ids)} others on {scope} overlap these dates" if people
                 else f"None of {len(peer_ids)} others on {scope} is away on these dates"),
        "rows": [{"reference": a.reference, "code": a.employee.code, "nameEn": a.employee.name_en,
                  "type": a.leave_type.code, "typeName": a.leave_type.name, "from": a.from_date.isoformat(),
                  "to": a.to_date.isoformat(), "state": "STATUTORY" if a.non_refusable else
                  ("APPROVED" if a.status == S.APPROVED else "WAITING")} for a in away],
        "statutory": [a.employee.name_en for a in away if a.non_refusable],
    }


def approvals(company, user=None):
    """§7. Each card: who and what, the breakdown, the balance position the
    button will test against (net of every OTHER hold), any warning, and the
    clash block."""
    today = clock.today()
    book = Book()
    rows = []
    qs = (LeaveRequest.objects.filter(company=company, status=S.SUBMITTED)
          .select_related("employee__department", "employee__designation", "leave_type", "cycle", "cover_employee",
                          "company").order_by("from_date"))
    for req in qs:
        ltype = req.leave_type
        p = position(req.employee, ltype, max(today, req.cycle.starts_on),
                     cycle=req.cycle if ltype.cycle_kind != "ROLLING" else None, exclude_request=req, book=book)
        tight = req.days_consumed > p.spendable and not ltype.allow_negative_balance
        warnings = []
        if tight and req.is_advance:
            warnings.append("An advance: approving takes the balance below zero.")
        elif tight:
            warnings.append("The balance no longer covers this request; approving is refused until it does.")
        if req.is_backdated:
            warnings.append(f"Entered after the leave began on {fmt(req.from_date)}.")
        if ltype.requires_medical_cert and req.days_consumed > 2 and not req.evidence:
            warnings.append("More than two days of sick leave: ask for a medical certificate.")
        own = bool(user is not None and req.employee.user_id and req.employee.user_id == user.pk)
        if own:
            warnings.append("This is your own leave: someone else decides it.")
        rows.append({**request_out(req, today), "position": p.out(),
                     "positionSentence": position_sentence(p, ltype, "free"), "tight": tight, "warnings": warnings,
                     "clash": clashes_for(req), "selfApproval": own})
    return {"rows": rows, "count": len(rows)}


def away_month(company, month, dept=None):
    """§8. A month strip per person with something in it, and the nearest
    month that has an absence when this one is empty."""
    import calendar as pycal

    first = month
    last = month.replace(day=pycal.monthrange(month.year, month.month)[1])
    everyone = roster(company)
    if dept:
        everyone = everyone.filter(department__uid=dept)
    ids = list(everyone.values_list("pk", flat=True))
    away = who_is_away(company, first, last, ids)
    people = {}
    for a in away:
        row = people.setdefault(a.employee_id, {**employee_out(a.employee), "bars": []})
        row["bars"].append({
            "reference": a.reference, "type": a.leave_type.code, "typeName": a.leave_type.name,
            "from": max(a.from_date, first).isoformat(), "to": min(a.to_date, last).isoformat(),
            "startsHere": a.from_date >= first, "endsHere": a.to_date <= last,
            "pending": a.status == S.SUBMITTED, "nonRefusable": a.non_refusable, "days": days_str(a.days_consumed),
        })
    nearest = None
    if not people:
        later = (LeaveRequest.objects.filter(company=company, status__in=[S.SUBMITTED, S.APPROVED],
                                             employee_id__in=ids, from_date__gt=last).order_by("from_date")
                 .values_list("from_date", flat=True).first())
        earlier = (LeaveRequest.objects.filter(company=company, status__in=[S.SUBMITTED, S.APPROVED],
                                               employee_id__in=ids, to_date__lt=first).order_by("-to_date")
                   .values_list("to_date", flat=True).first())
        pick = later or earlier
        nearest = pick.strftime("%Y-%m") if pick else None
    return {"month": first.strftime("%Y-%m"), "days": [d for d in range(1, last.day + 1)],
            "rows": sorted(people.values(), key=lambda r: r["nameEn"]), "rosterCount": len(ids), "nearest": nearest,
            "weekdays": [date(first.year, first.month, d).isoweekday() for d in range(1, last.day + 1)]}


def nearest_month_with_absence(company, around):
    """The opening month (§8.3): this month if anything is in it, else the
    nearest future month with something, else the nearest past one."""
    qs = LeaveRequest.objects.filter(company=company, status__in=[S.SUBMITTED, S.APPROVED])
    first = around.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    if qs.filter(from_date__lt=nxt, to_date__gte=first).exists():
        return first
    later = qs.filter(from_date__gte=nxt).order_by("from_date").values_list("from_date", flat=True).first()
    if later:
        return later.replace(day=1)
    earlier = qs.filter(to_date__lt=first).order_by("-to_date").values_list("to_date", flat=True).first()
    return earlier.replace(day=1) if earlier else first


# ==================================================================== history


def entry_out(e):
    return {
        "uid": str(e.uid), "reference": e.reference, "type": e.leave_type.code, "date": e.effective_date.isoformat(),
        "days": days_str(e.days), "reason": e.reason, "reasonLabel": e.get_reason_display(), "basis": e.basis,
        "basisBn": e.basis_bn or None, "sourceRef": e.source_ref or None, "ruleSet": e.rule_set.version,
        "by": e.created_by_name or None, "at": e.created_at.isoformat(), "onBehalf": e.on_behalf,
        "reversedBy": f"LEDG-{e.reversed_by_id:06d}" if e.reversed_by_id else None,
        "counts": e.reversed_by_id is None and e.reason != R.REVERSAL,
        "cycle": {"from": e.cycle.starts_on.isoformat(), "to": e.cycle.ends_on.isoformat(), "kind": e.cycle.kind},
    }


def history(company, employee, code="ALL"):
    """§9.3. Newest first, a running balance per leave type and cycle, a
    reason on every line. A reversed entry stays visible and stops counting."""
    today = clock.today()
    types = ensure_types(company)
    refresh_credits(company, today, [employee])
    qs = (LedgerEntry.objects.filter(company=company, employee=employee)
          .select_related("leave_type", "cycle", "rule_set").order_by("effective_date", "id"))
    if code != "ALL":
        qs = qs.filter(leave_type__code=code.upper())
    running = {}
    rows = []
    for e in qs:
        key = (e.leave_type_id, e.cycle_id if e.cycle.kind != "ROLLING" else 0)
        if e.reversed_by_id is None and e.reason != R.REVERSAL:
            running[key] = running.get(key, ZERO) + e.days
        rows.append({**entry_out(e), "running": days_str(running.get(key, ZERO))})
    rows.reverse()
    book = Book()
    shown = [t for t in types.values() if t.code != "MATERNITY"]
    pos = Positions(company, [employee], shown, today, book)
    return {
        "employee": employee_out(employee),
        "positions": {t.code: {**pos.of(employee, t).out(), "name": t.name} for t in shown},
        "rows": rows,
        "requests": [request_out(r, today) for r in LeaveRequest.objects.filter(company=company, employee=employee)
                     .select_related("employee__department", "employee__designation", "leave_type", "cover_employee",
                                     "ledger_entry").order_by("-from_date")[:50]],
    }


# ================================================================= encashment


def encashment_out(enc, figures):
    return {
        "reference": enc.reference, "employee": employee_out(enc.employee), "days": days_str(enc.days),
        "status": enc.status, "divisor": enc.divisor, "rateBasis": enc.rate_basis,
        "wageBase": money_str(enc.wage_base) if figures else None,
        "dailyRate": money_str(enc.daily_rate) if figures else None,
        "amount": money_str(enc.amount) if figures else None, "masked": not figures,
        "requestedBy": enc.requested_by_name or None, "requestedAt": enc.created_at.isoformat(),
        "approvedBy": enc.approved_by_name or None, "approvedAt": enc.approved_at.isoformat() if enc.approved_at else None,
        "declineReason": enc.decline_reason or None,
        "paymentMonth": enc.payment_month.strftime("%Y-%m") if enc.payment_month else None,
        "payrollRef": enc.payroll_ref or None, "payslipRef": enc.payslip_ref or None,
        "entry": enc.ledger_entry.reference if enc.ledger_entry_id else None,
        "cycle": {"from": enc.cycle.starts_on.isoformat(), "to": enc.cycle.ends_on.isoformat()},
    }


def encashments(company, figures):
    qs = (Encashment.objects.filter(company=company)
          .select_related("employee__department", "employee__designation", "cycle", "ledger_entry"))
    rows = [encashment_out(x, figures) for x in qs]
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"rows": rows, "counts": counts, "masked": not figures}


# ================================================================== maternity


def maternity_out(case):
    """No restricted field, ever: they are read one at a time, logged."""
    return {
        "reference": case.reference, "employee": employee_out(case.employee), "status": case.status,
        "noticeDate": case.notice_date.isoformat(), "noticeMethod": case.notice_method,
        "noticeRecordedBy": case.notice_recorded_by_name or None,
        "leaveFrom": case.pre_leave_from.isoformat(), "leaveTo": case.post_leave_to.isoformat(),
        "totalDays": case.total_days_granted, "benefitPayable": case.benefit_payable,
        "eligibility": case.eligibility_reason, "serviceMonths": case.service_months,
        "serviceMonthsMet": case.service_months_met,
        "protectionStart": case.protection_start.isoformat(), "protectionEnd": case.protection_end.isoformat(),
        "employmentBanEnd": case.employment_ban_end.isoformat(), "request": case.request.reference,
        "deliveryRecorded": case.actual_delivery is not None,
    }


def maternity_cases(company):
    qs = MaternityCase.objects.filter(company=company).select_related("employee__department",
                                                                      "employee__designation", "request")
    return {"rows": [maternity_out(c) for c in qs]}


# ===================================================================== policy


def policy(company, as_of=None):
    """§7 tab: the rule set in force, read-only, with every figure's citation
    and how sure the rule book is of it."""
    as_of = as_of or clock.today()
    book = Book()
    rules = book.rules(as_of)
    types = ensure_types(company)
    ests = sorted(rules.el_divisor)
    return {
        "asOf": as_of.isoformat(), "ruleSet": rules.version, "confidence": rules.confidence,
        "effectiveFrom": rules.rule_set.effective_from.isoformat(),
        "source": getattr(rules.rule_set, "source", "") or None,
        "types": [type_out(t, rules) for t in types.values()],
        "establishments": [{"establishment": est, "divisor": rules.el_divisor.get(est),
                            "divisorAdolescent": rules.el_divisor_adolescent.get(est), "cap": rules.el_cap.get(est)}
                           for est in ests],
        "rows": rules.rows,
    }
