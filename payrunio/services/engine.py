"""`computeLine` (run payroll §4.6). Pure: every input is explicit in a
`LineInput`, with no clock read and no database access, so the same input
gives the same line on any machine in any year (§5.2).

Rounding (payroll settings §4.4): each earnings line once, by the rounding
election, never below its paisa figure; gross is the sum of the rounded
lines, so the payslip adds up. Overtime's hourly rate is an intermediate and
is kept to four places. Tax arrives rounded to the taka by the projection.
PF is rounded half-up to the taka (to the paisa under PAISA), the same rule
for both sides so the employer's match equals the employee's (s.264).

Overtime sits outside the proration factor: extra hours are earned on the
full monthly s.108 base, not on a share of a reduced month.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from common.words import format_date, format_money
from paysetio.services.resolve import round_line

from ..choices import DEDUCTION_ORDER, ENGINE_VERSION, EXCEPTION_CODES

ZERO = Decimal("0")
FOUR = Decimal("0.0001")
TAKA = Decimal("1")
PAISA = Decimal("0.01")


@dataclass(frozen=True)
class LineInput:
    employee_code: str
    employee_name: str
    classification: str
    period_start: object
    period_end: object
    calendar_days: int
    join_in_period: object = None
    leave_in_period: object = None
    lwp_days: Decimal = ZERO
    payable_days: Decimal = ZERO
    days_lost: Decimal = ZERO
    factor: Decimal = Decimal(1)
    method: str = ""  # the proration election

    structure_uid: str = ""
    components: tuple = ()  # ((code, label, monthly amount), …)
    monthly_gross: Decimal = ZERO
    monthly_basic: Decimal = ZERO
    floor_failures: tuple = ()  # ((message, citation), …) on the full monthly rate

    ot_hours: Decimal = ZERO
    ot_base: Decimal = ZERO
    ot_base_label: str = ""
    month_hours: Decimal = Decimal(208)
    ot_multiplier: Decimal = Decimal(2)

    pf_base: Decimal = ZERO
    pf_employee_pct: object = None  # None: not a member
    pf_employer_pct: object = None

    tax_period: object = None  # this period's withholding; None: no projection
    ytd_tax: Decimal = ZERO

    rounding: str = "TAKA"
    payment_method: str = "BANK_TRANSFER"
    has_destination: bool = True
    on_hold: bool = False
    hold_reason: str = ""
    has_etin: bool = True

    rule_set: str = ""
    tax_card: str = ""
    elections_hash: str = ""
    other: dict = field(default_factory=dict)  # requested ADVANCE/LOAN/OTHER, by code


@dataclass
class LineResult:
    gross: Decimal = ZERO
    ot_amount: Decimal = ZERO
    ot_base: Decimal = ZERO
    tax: Decimal = ZERO
    pf_employee: Decimal = ZERO
    pf_employer: Decimal = ZERO
    other: Decimal = ZERO
    net: Decimal = ZERO
    earnings: list = field(default_factory=list)
    deductions: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)  # [{code, severity, message, citation}]
    input_hash: str = ""


def money(v):
    return format_money(Decimal(v).quantize(TAKA, rounding=ROUND_HALF_UP), places=0)


def s(v):
    return format(Decimal(v), "f")


def _canon(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in sorted(value.items())}
    return value


def input_hash(inp):
    """§5.2: everything that moves a figure, plus the engine version. The
    same hash with a different net is drift: an engine defect."""
    body = _canon({**asdict(inp), "engine": ENGINE_VERSION})
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _exc(code, message, citation=""):
    return {"code": code, "severity": EXCEPTION_CODES[code], "message": message, "citation": citation}


def _pf(base, pct, factor, rounding):
    if pct is None:
        return ZERO
    raw = base * factor * Decimal(str(pct)) / 100
    return raw.quantize(PAISA if rounding == "PAISA" else TAKA, rounding=ROUND_HALF_UP)


def apply_deductions(gross, requested):
    """§4.5, in the statutory order, against the remaining wage. A protected
    deduction is never reduced; any other that would take the net below zero
    is deferred, not clipped."""
    applied, deferred, running = [], [], ZERO
    for d in DEDUCTION_ORDER:
        amount = requested.get(d["code"])
        if not amount:
            continue
        amount = Decimal(amount)
        if d["protected"] or running + amount <= gross:
            applied.append({**d, "amount": amount})
            running += amount
        else:
            deferred.append({**d, "amount": amount,
                             "reason": "It would take the net below zero; it is carried to the next period."})
    return applied, deferred, running


def compute_line(inp):
    r = LineResult(input_hash=input_hash(inp))
    f = Decimal(inp.factor)
    for code, label, monthly in inp.components:
        monthly = Decimal(monthly)
        amount = round_line(monthly * f, inp.rounding)
        r.earnings.append({"code": code, "label": label, "monthly": s(monthly), "amount": s(amount),
                           "basis": f"{money(monthly)} per month" if f == 1 else
                           f"{money(monthly)} × {s((f * 100).quantize(Decimal('0.1')))}%"})
        r.gross += amount

    if inp.ot_hours and inp.ot_base:
        hourly = (Decimal(inp.ot_base) / Decimal(inp.month_hours)).quantize(FOUR, rounding=ROUND_HALF_UP)
        r.ot_base = Decimal(inp.ot_base)
        r.ot_amount = round_line(hourly * Decimal(inp.ot_multiplier) * Decimal(inp.ot_hours), inp.rounding)
        r.earnings.append({"code": "OT", "label": "Overtime", "monthly": None, "amount": s(r.ot_amount),
                           "basis": f"{s(inp.ot_hours)} hours × {format_money(hourly, places=2)} × "
                                    f"{s(inp.ot_multiplier)} · s.108 base ({inp.ot_base_label})"})
        r.gross += r.ot_amount

    r.pf_employee = _pf(inp.pf_base, inp.pf_employee_pct, f, inp.rounding)
    r.pf_employer = _pf(inp.pf_base, inp.pf_employer_pct, f, inp.rounding)
    tax = Decimal(inp.tax_period) if inp.tax_period is not None else ZERO
    requested = {"TAX": tax, "PF": r.pf_employee, **{k: Decimal(v) for k, v in inp.other.items()}}
    applied, deferred, total = apply_deductions(r.gross, requested)
    r.tax = next((d["amount"] for d in applied if d["code"] == "TAX"), ZERO)
    r.other = sum((d["amount"] for d in applied if d["code"] not in ("TAX", "PF")), ZERO)
    for d in applied:
        note = ("Instalment on the annual projection, re-derived every month (s.86)." if d["code"] == "TAX"
                else f"{s(inp.pf_employee_pct)}% of the PF base, matched by the employer." if d["code"] == "PF"
                else "")
        r.deductions.append({"n": d["n"], "code": d["code"], "label": d["label"], "bn": d["bn"], "amount": s(d["amount"]),
                             "note": note, "deferred": False, "citation": d["citation"]})
    for d in deferred:
        r.deductions.append({"n": d["n"], "code": d["code"], "label": d["label"], "bn": d["bn"], "amount": "0",
                             "note": d["reason"], "deferred": True, "citation": d["citation"]})
        r.exceptions.append(_exc("DEDUCTION_DEFERRED", f"{d['label']} of {money(d['amount'])} was deferred. "
                                                       f"{d['reason']}", d["citation"]))

    net = r.gross - total
    r.net = max(ZERO, net)
    if net <= 0:
        r.exceptions.append(_exc("NET_NOT_POSITIVE", f"Net pay is {money(net)}. Deductions of {money(total)} have "
                                                     f"consumed the whole wage of {money(r.gross)}, which no order "
                                                     "permits.", "Bangladesh Labour Act 2006, s.125"))
    for message, citation in inp.floor_failures:
        part = " The shortfall is in the rate, not the part month." if f < 1 else ""
        r.exceptions.append(_exc("BELOW_GRADE_FLOOR", message + part, citation))
    if inp.on_hold:
        r.exceptions.append(_exc("SALARY_ON_HOLD", f"Salary is on hold{': ' + inp.hold_reason if inp.hold_reason else ''}. "
                                                   "Exclude the line and pay it on a supplementary run when the hold "
                                                   "lifts."))
    if inp.payment_method == "CASH":
        r.exceptions.append(_exc("CASH_PAYMENT", "Paid in cash. Lawful under the Labour Act, but salary outside a "
                                                 "banking channel is disallowed to the employer.",
                                 "Income Tax Act 2023, s.55"))
    elif not inp.has_destination:
        what = "bank transfer with no account or routing number" if inp.payment_method == "BANK_TRANSFER" \
            else "mobile wallet with no wallet number"
        r.exceptions.append(_exc("MISSING_BANK_DETAIL", f"Payment method is {what} on file. Add it in the employee's "
                                                        "payment profile, or exclude the line."))
    if not inp.has_etin and r.tax > 0:
        r.exceptions.append(_exc("NO_ETIN", f"No e-TIN on file, and {money(r.tax)} is withheld. The withholding "
                                            "certificate needs the TIN; the higher withholding rate for a missing TIN "
                                            "is not applied by this engine."))
    if inp.days_lost > 0:
        why = []
        if inp.join_in_period:
            why.append(f"joined {format_date(inp.join_in_period)}")
        if inp.leave_in_period:
            why.append(f"left {format_date(inp.leave_in_period)}")
        if inp.lwp_days:
            n = s(Decimal(inp.lwp_days).normalize())
            why.append(f"{n} day{'' if Decimal(inp.lwp_days) == 1 else 's'} leave without pay")
        lost = s(Decimal(inp.days_lost).normalize())
        r.exceptions.append(_exc("PRORATED", f"Paid for {s(Decimal(inp.payable_days).normalize())} of "
                                             f"{inp.calendar_days} days — {', '.join(why) or 'unpaid absence'}; "
                                             f"{lost} day{'' if Decimal(inp.days_lost) == 1 else 's'} not payable. "
                                             f"Paid at {s((f * 100).quantize(Decimal('0.1')))}% of the monthly rate "
                                             f"({inp.method.replace('_', ' ').lower()})."))
    return r
