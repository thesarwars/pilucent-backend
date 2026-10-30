"""Everything a line is computed from, read once (run payroll §4.2-§4.4).

The engine is pure; this is where the database is read. The elections come
from the run's frozen snapshot, never re-resolved (§3.4). Payable days come
from the attendance period the run consumed: leave without pay is READ from
the locked day snapshots, never typed (non-negotiable 6), and so is the
overtime, unless the payroll officer overrode it for this run.
"""

import hashlib
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from common.money import ZERO, to_decimal
from employeeio.choices import SalaryComponentChoices
from employeeio.services.salary import floor_checks, structure_in_force
from employeeio.services.statutory import line_base, proration_factor
from employeeio.services.tax import income_year_start, project
from paysetio.services.ops import participation_in_force, scheme_config
from paysetio.services.resolve import Hypothetical, overtime_base

from ..choices import FIXED, METHOD_OF_PROFILE
from .engine import LineInput

LABELS = dict(SalaryComponentChoices.choices)
LWP = "LEAVE_WITHOUT_PAY"
HOURS = Decimal("0.01")


# ================================================================ elections


def snapshot(resolved, labour):
    """§3.4: the seven elections as resolved, plus the month hours the
    overtime divisor uses (the election's, else the rule book's 208)."""
    from paysetio.services.resolve import month_hours

    from django.utils import timezone

    class _Book:  # month_hours reads book.labour
        def __init__(self, view):
            self.labour = view

    return {"elections": {k: r.as_dict() for k, r in resolved.items()},
            "standardMonthHours": format(month_hours(resolved["overtime_base"], _Book(labour)), "f"),
            "resolvedAt": timezone.now().isoformat()}


def snapshot_hash(snap):
    body = {k: v for k, v in snap.items() if k != "resolvedAt"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def frozen(snap, key):
    e = snap["elections"][key]
    return Hypothetical(key, e["value"], e.get("data") or {}, e.get("standardMonthHours"))


# ================================================================ attendance


def attendance(run, employees):
    """{employee_id: {"lwp": days, "ot": hours}} from the locked period."""
    from timekeepingio.models import AttendancePeriod, DaySnapshot

    period = AttendancePeriod.objects.filter(site=run.site, period_month=run.period_start).first()
    out = defaultdict(lambda: {"lwp": ZERO, "ot": ZERO, "lwpDays": []})
    if period is None:
        return out
    minutes = defaultdict(int)
    rows = DaySnapshot.objects.filter(period=period, employee__in=employees,
                                      business_date__range=(run.period_start, run.period_end))
    for emp_id, d, status, ot in rows.values_list("employee_id", "business_date", "status", "overtime_minutes"):
        if status == LWP:
            out[emp_id]["lwpDays"].append(d)
        minutes[emp_id] += ot or 0
    for emp_id, m in minutes.items():
        out[emp_id]["ot"] = (Decimal(m) / 60).quantize(HOURS, rounding=ROUND_HALF_UP)
    return out


def team(run):
    """Everyone on the site in employment for some part of the period."""
    from django.db.models import Q

    from timekeepingio.services.base import site_employees

    return (site_employees(run.company, run.site)
            .filter(Q(doj__isnull=True) | Q(doj__lte=run.period_end))
            .filter(Q(separated_on__isnull=True) | Q(separated_on__gte=run.period_start)))


# ================================================================== payment


def payment_of(employee):
    """(method, provider, has_destination, masked destination, on_hold, hold_reason)."""
    from employeeio.models import EmployeePaymentProfile

    try:
        p = employee.payment
    except EmployeePaymentProfile.DoesNotExist:
        return "BANK_TRANSFER", "", False, "", False, ""
    method = METHOD_OF_PROFILE.get(p.method, "BANK_TRANSFER")
    if method == "BANK_TRANSFER":
        ok = bool(p.account_number) and bool(p.routing)
        dest = f"{p.bank or 'Bank'} •••• {p.account_number[-4:]}" if p.account_number else ""
    elif method == "MOBILE_WALLET":
        ok = bool(p.wallet_number)
        dest = f"{p.get_mfs_provider_display() or 'Wallet'} •••• {p.wallet_number[-4:]}" if p.wallet_number else ""
    else:
        ok, dest = True, "Cash, against signature"
    return method, (p.mfs_provider or ""), ok, dest, p.on_hold, p.hold_reason or ""


def destination_row(line, employee, narration):
    """The bank-file row: the live account details, which the masked
    `destination_ref` on the line stands for."""
    from employeeio.models import EmployeePaymentProfile

    try:
        p = employee.payment
    except EmployeePaymentProfile.DoesNotExist:
        p = None
    return {"employeeRef": employee.code, "employeeName": employee.name_en,
            "accountName": (p.account_name if p and p.account_name else employee.name_en),
            "accountNumber": p.account_number if p else "", "routingNumber": p.routing if p else "",
            "walletNumber": p.wallet_number if p else "", "amount": line.net_pay, "narration": narration,
            "signature": ""}


# ====================================================================== tax


def ytd_tax(employee, run):
    """Tax withheld for the employee earlier in the income year, by runs
    whose figures are fixed."""
    from django.db.models import Sum

    from ..models import PayrollRunLine

    start = income_year_start(run.period_start)
    total = (PayrollRunLine.objects.filter(employee=employee, included=True, run__state__in=list(FIXED),
                                           run__period_start__gte=start, run__period_start__lt=run.period_start)
             .aggregate(t=Sum("tax_withheld"))["t"])
    return to_decimal(total or 0)


# ===================================================================== line


class NoStructure(Exception):
    pass


def days(run, employee, att):
    """§4.2: (calendar, payable, lost, lwp, join in period, leave in period)."""
    calendar_days = (run.period_end - run.period_start).days + 1
    join = employee.doj if employee.doj and run.period_start < employee.doj <= run.period_end else None
    leave = employee.separated_on if employee.separated_on and \
        run.period_start <= employee.separated_on < run.period_end else None
    start, end = join or run.period_start, leave or run.period_end
    lwp = Decimal(sum(1 for d in att["lwpDays"] if start <= d <= end))
    window = Decimal((end - start).days + 1)
    payable = max(ZERO, window - lwp)
    return calendar_days, payable, Decimal(calendar_days) - payable, lwp, join, leave


def gather(run, line, employee, book, calendar, att):
    """The `LineInput` for one employee, or `NoStructure`."""
    snap = run.elections_snapshot
    calendar_days, payable, lost, lwp, join, leave = days(run, employee, att)
    method = snap["elections"]["proration_method"]["value"]
    structure = structure_in_force(employee, run.period_end) or structure_in_force(employee, run.period_start)
    if structure is None:
        raise NoStructure(f"No salary structure in force for {run.period_start:%B %Y}.")
    factor = proration_factor(run.period_start, method, book, join_date=join, leave_date=leave, lwp_days=lwp,
                              calendar=calendar)
    comps = tuple((c.code, LABELS.get(c.code, c.code), to_decimal(c.amount)) for c in structure.components.all())
    gross = sum((a for _, _, a in comps), ZERO)
    basic = sum((a for c, _, a in comps if c == "BASIC"), ZERO)

    ot_total, _, ot_label = overtime_base(structure, frozen(snap, "overtime_base"))
    pf_base, _ = line_base(structure, "in_pf_base")
    member = participation_in_force(employee, "PF", run.period_end)
    pf_emp = pf_er = None
    if member is not None:
        cfg = scheme_config(run.company, "PF", run.period_end) or {}
        pf_emp = member.override_rate_pct if member.override_rate_pct is not None else cfg.get("employeeRatePct")
        pf_er = member.override_employer_rate_pct if member.override_employer_rate_pct is not None \
            else cfg.get("employerRatePct")
        pf_emp = to_decimal(pf_emp) if pf_emp is not None else None
        pf_er = to_decimal(pf_er) if pf_er is not None else None

    ytd = ytd_tax(employee, run)
    proj = project(employee, as_of=run.period_end, book=book, ytd_deducted=ytd)
    tax = proj.figures["periodDeduction"].value if proj.available else None

    failures = ()
    if employee.classification == "WORKER":
        failures = tuple((c["message"], c["citation"] or "") for c in floor_checks(employee.grade, basic, gross, book)
                         if not c["passed"])

    pm, provider, has_dest, _, on_hold, hold_reason = payment_of(employee)
    try:
        etin = bool(employee.tax_profile.etin)
    except Exception:  # noqa: BLE001 -- no tax profile on file
        etin = False

    ot_hours = line.ot_hours if line.ot_hours_source == "MANUAL_OVERRIDE" else att["ot"]
    inp = LineInput(
        employee_code=employee.code, employee_name=employee.name_en, classification=employee.classification or "",
        period_start=run.period_start, period_end=run.period_end, calendar_days=calendar_days,
        join_in_period=join, leave_in_period=leave, lwp_days=lwp, payable_days=payable, days_lost=lost,
        factor=factor, method=method, structure_uid=str(structure.uid), components=comps, monthly_gross=gross,
        monthly_basic=basic, floor_failures=failures, ot_hours=to_decimal(ot_hours), ot_base=ot_total,
        ot_base_label=ot_label, month_hours=Decimal(snap["standardMonthHours"]),
        ot_multiplier=book.labour.decimal("overtimeMultiplier"), pf_base=pf_base, pf_employee_pct=pf_emp,
        pf_employer_pct=pf_er, tax_period=tax, ytd_tax=ytd, rounding=snap["elections"]["rounding_mode"]["value"],
        payment_method=pm, has_destination=has_dest, on_hold=on_hold, hold_reason=hold_reason, has_etin=etin,
        rule_set=str(run.rule_set.uid), tax_card=str(run.tax_card.uid), elections_hash=snapshot_hash(snap),
    )
    return inp, structure, proj
