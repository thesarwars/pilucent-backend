"""Statutory computations (doc §7.1-§7.4) and the separation higher-of test
(§6.3). Ported from the front end's `calc.js` and `payroll-calc.js`; every
number comes from the rule book in force on the date asked about.

Every figure is a `Figure` -- `{value, basis, citation, confidence}` on the
wire (§9) -- whose confidence is the lowest of the rules it rests on.

Rounding points (common.money): gratuity and compensation are rounded to the
taka where the basis says so; display rates (overtime per hour, a provision
per month, a day's encashment) to the paisa. Nothing in between is rounded.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from common.money import ZERO, round_to_paisa, round_to_taka, to_decimal
from rulebookio.book import UnknownRule

from ..choices import GratuityBasisChoices, ProrationDivisorChoices, SalaryComponentChoices, SeparationTypeChoices
from .periods import days_in_month, month_end, month_start
from .profile import add_months, service_parts
from .tax import Figure

MONTHS_PER_YEAR = 12


# ------------------------------------------------------------- gratuity §7.1


@dataclass
class Gratuity:
    years: int
    rounded_up: bool
    days: int
    service: object  # ServiceParts
    base: Figure
    amount: Figure
    monthly_provision: Figure

    def as_dict(self):
        return {
            "years": self.years,
            "roundedUp": self.rounded_up,
            "daysPerYear": self.days,
            "service": self.service.as_dict(),
            "base": self.base.as_dict(),
            "amount": self.amount.as_dict(),
            "monthlyProvision": self.monthly_provision.as_dict(),
        }


def gratuity_rules(book):
    L = book.labour
    return {
        "standard": L.get("gratuityDaysStandard"),
        "after": L.get("gratuityDaysAfterBreakpoint"),
        "breakpoint": L.get("gratuityYearBreakpoint"),
        "fraction": L.get("gratuityFractionMonths"),
        "divisor": L.get("dayWageDivisor"),
    }


def gratuity_years(parts, book):
    """Completed years, with a part-year over `gratuityFractionMonths` rounding
    UP -- measured to the day, so 6y 6m 20d counts as 7 (DEF-06). Floor-
    dividing months counted it as 6, understating exactly the records built to
    test it."""
    fraction = int(book.labour.value("gratuityFractionMonths"))
    over = parts.residual_months > fraction or (parts.residual_months == fraction and parts.residual_days > 0)
    return parts.years + (1 if over else 0), over


def gratuity_days(years, book):
    rules = gratuity_rules(book)
    return int(rules["after"].value if years > int(rules["breakpoint"].value) else rules["standard"].value)


def wage_base(employee, structure):
    """`gratuityBasis` = GROSS ? monthly gross : basic (§7.1)."""
    if employee.statutory.gratuity_basis == GratuityBasisChoices.GROSS:
        return structure.gross, "monthly gross (gratuity basis GROSS)"
    return structure.basic, "basic"


def gratuity(employee, structure, until, book):
    rules = gratuity_rules(book)
    parts = service_parts(employee.doj, until)
    years, rounded_up = gratuity_years(parts, book)
    days = gratuity_days(years, book)
    divisor = rules["divisor"].decimal
    base_value, base_label = wage_base(employee, structure)
    base = Figure(base_value, f"Last drawn {base_label}")
    service = f"{parts.years}y {parts.residual_months}m {parts.residual_days}d"
    amount = Figure(
        round_to_taka(base_value * days * years / divisor),
        f"{base_label.capitalize()} ÷ {rules['divisor'].value} × {days} days × {years} years "
        f"({service}{', part-year over ' + str(rules['fraction'].value) + ' months rounds up' if rounded_up else ''}); "
        "rounded to the taka",
        list(rules.values()), [base],
    )
    # One year's gratuity spread over twelve months (calc.js `salDerive`): the
    # charge the employer accrues each month, not the accrued total ÷ 12.
    monthly = Figure(
        round_to_paisa(base_value * days / divisor / MONTHS_PER_YEAR),
        f"{base_label.capitalize()} ÷ {rules['divisor'].value} × {days} days ÷ {MONTHS_PER_YEAR}",
        [rules["standard"], rules["after"], rules["breakpoint"], rules["divisor"]], [base],
    )
    return Gratuity(years, rounded_up, days, parts, base, amount, monthly)


def gratuity_breakpoint(employee, structure, as_of, book):
    """When the days per year step up (§7.1), so the UI can warn that the
    provision is about to rise. None once it has.

    `anniversary` is the breakpoint anniversary; `ratesRiseOn` is the first
    day the higher rate applies, which with the part-year rounding is the day
    after breakpoint years plus the fraction months.
    """
    if employee.doj is None:
        return None
    rules = gratuity_rules(book)
    breakpoint = int(rules["breakpoint"].value)
    rises_on = add_months(employee.doj, breakpoint * MONTHS_PER_YEAR + int(rules["fraction"].value)) + timedelta(days=1)
    if rises_on <= as_of:
        return None
    base_value, base_label = wage_base(employee, structure)
    after = int(rules["after"].value)
    return {
        "anniversary": add_months(employee.doj, breakpoint * MONTHS_PER_YEAR).isoformat(),
        "ratesRiseOn": rises_on.isoformat(),
        "withinTwelveMonths": rises_on <= add_months(as_of, MONTHS_PER_YEAR),
        "daysFrom": int(rules["standard"].value),
        "daysTo": after,
        "monthlyProvisionAfter": Figure(
            round_to_paisa(base_value * after / rules["divisor"].decimal / MONTHS_PER_YEAR),
            f"{base_label.capitalize()} ÷ {rules['divisor'].value} × {after} days ÷ {MONTHS_PER_YEAR}, "
            f"once service passes {breakpoint} years",
            list(rules.values()),
        ).as_dict(),
    }


# ------------------------------------------------------------- overtime §7.2


def overtime_hourly(structure, book):
    """2 × the ordinary hourly rate, on basic + DA only (s.108) -- the FULL
    monthly amount, not a prorated one."""
    multiplier = book.labour.get("overtimeMultiplier")
    hours = book.labour.get("standardMonthHours")
    base = structure.basic + structure.component_amount(SalaryComponentChoices.DA)
    return Figure(
        round_to_paisa(base * multiplier.decimal / hours.decimal),
        f"(Basic + DA) {base} ÷ {hours.value} hours × {multiplier.value}; shown to the paisa",
        [multiplier, hours],
    )


# ------------------------------------------------------- festival bonus §7.3


def festival_bonus(employee, structure, as_of, book):
    L = book.labour
    months = L.get("festivalBonusServiceMonths")
    per_year = L.get("festivalBonusesPerYear")
    cap = L.get("festivalBonusCapMultiple")
    per_bonus = structure.basic * cap.decimal
    eligible_from = add_months(employee.doj, int(months.value)) if employee.doj else None
    try:
        taxable = book.tax.get("festivalBonusTaxable")
    except UnknownRule:
        taxable = None
    return {
        "eligibleFrom": eligible_from.isoformat() if eligible_from else None,
        "eligible": bool(eligible_from and eligible_from <= as_of),
        "perBonus": Figure(per_bonus, f"Basic × {cap.value}", [cap]).as_dict(),
        "annual": Figure(per_bonus * per_year.decimal, f"Per bonus × {per_year.value} festivals",
                         [cap, per_year]).as_dict(),
        "monthlyProvision": Figure(
            round_to_paisa(per_bonus * per_year.decimal / MONTHS_PER_YEAR),
            f"Per bonus × {per_year.value} ÷ {MONTHS_PER_YEAR}", [cap, per_year]).as_dict(),
        "serviceMonths": int(months.value),
        "taxable": Figure(taxable.value, "Fully taxable — no exemption; under-withheld most often in "
                          "March and September", [taxable]).as_dict(money=False) if taxable else None,
    }


# ----------------------------------------------------------------- leave §7.4


def earned_leave_accrual(days_worked, establishment, book):
    """1 day per `ratio` days worked, whole days only (calc.js `leaveAccrual`).
    Throws on an establishment the rule book does not know rather than
    letting a missing ratio through as a number."""
    ratios = book.labour.get("earnedLeaveRatioByEstablishment")
    if establishment not in ratios.value:
        raise UnknownRule(f"No earned-leave ratio for establishment {establishment!r}.")
    return int(days_worked) // int(ratios.value[establishment])


def leave(employee, structure, book):
    L = book.labour
    ratios = L.get("earnedLeaveRatioByEstablishment")
    caps = L.get("accumulationCapByEstablishment")
    divisor = L.get("dayWageDivisor")
    max_percent = L.get("encashmentMaxPercent")
    per_year = L.get("encashmentPerYear")
    est = employee.establishment
    count = lambda rv: Figure(rv.value, rv.note or "", [rv]).as_dict(money=False)  # noqa: E731
    return {
        "establishment": est or None,
        "earnedLeaveRatio": Figure(
            ratios.value[est], f"1 day of earned leave per {ratios.value[est]} days worked ({est})", [ratios]
        ).as_dict(money=False) if est in ratios.value else None,
        "accumulationCap": Figure(
            caps.value[est], f"Earned leave accumulates to at most {caps.value[est]} days ({est})", [caps]
        ).as_dict(money=False) if est in caps.value else None,
        "casualDays": count(L.get("casualLeaveDays")),
        "sickDays": count(L.get("sickLeaveDays")),
        "festivalHolidays": count(L.get("festivalHolidayDays")),
        "encashment": {
            "maxPercentOfBalance": count(max_percent),
            "timesPerYear": count(per_year),
            "dailyRate": Figure(
                round_to_paisa(structure.gross / divisor.decimal),
                f"Gross ÷ {divisor.value}", [divisor]).as_dict(),
        },
        "message": None if est else "No establishment recorded: the earned-leave ratio and cap depend on it.",
    }


# ------------------------------------------------------------ proration §11.13


def proration_factor(period, divisor, book, join_date=None, leave_date=None, lwp_days=0,
                     weekly_holidays_lost=0, payable_hours=None):
    """The share of a month's pay earned in `period` (payroll-calc.js 05.3).

    Driven by days LOST, not days present: a full unbroken period is 1.0
    whatever the calendar says. Dividing days present by 30 was right for a
    30-day month and silently underpaid every February by 6.7% (acceptance
    test 13). CALENDAR_ACTUAL is the one convention that genuinely pays by
    actual days, so it divides by the real month length.

    `weekly_holidays_lost` (WORKING_26 only): weekly holidays inside the days
    lost before joining or after leaving -- they were never working days, so
    they cost nothing. (The front end added them to the days lost, which
    docked a full month 4/26.)
    """
    start, end = month_start(period), month_end(period)
    first = max(start, join_date) if join_date else start
    last = min(end, leave_date) if leave_date else end
    if last < first:
        return ZERO
    lost = (first - start).days + (end - last).days + int(lwp_days)
    D = ProrationDivisorChoices
    if divisor == D.CALENDAR_ACTUAL:
        present = (last - first).days + 1 - int(lwp_days)
        return max(ZERO, Decimal(present) / Decimal(days_in_month(start)))
    if divisor == D.FIXED_30:
        return max(ZERO, 1 - Decimal(lost) / book.labour.decimal("dayWageDivisor"))
    if divisor == D.WORKING_26:
        lost_working = max(0, lost - int(weekly_holidays_lost))
        return max(ZERO, 1 - Decimal(lost_working) / book.labour.decimal("standardDaysPerMonth"))
    if divisor == D.HOURS_208:
        if payable_hours is None:
            raise ValueError("The HOURS_208 divisor needs the payable hours.")
        # Hours past the divisor are overtime, not a bigger month.
        return min(Decimal(1), max(ZERO, to_decimal(payable_hours) / book.labour.decimal("standardMonthHours")))
    raise ValueError(f"Unknown proration divisor: {divisor}")


# ------------------------------------------------------------ separation §6.3


def separation_entitlement(employee, structure, separation_type, on, book, gross_misconduct=False):
    """The higher-of test (calc.js `higherOfTest`), resolving a graduated rate
    BEFORE using it: a bare `days` is undefined for the graduated cases and
    silently produced NaN.

    Differences from calc.js:

    * Following the contract (§6.3), a graduated band is compared with
      gratuity only where the band itself says so (10+ years). calc.js applied
      the comparison to every band.
    * Eligibility -- the band, a minimum service, the death-compensation year
      -- is judged on COMPLETED years. Only the days x years multiplication
      counts a part-year over six months as a year; calc.js used the rounded
      count for both, so seven months' service qualified as a year.
    * The comparison is with "gratuity, if any" (s.20, s.26): an employee
      with no gratuity entitlement (`gratuityEligible` off) compares with nil.
    """
    L = book.labour
    grat = gratuity(employee, structure, on, book)
    years = grat.years
    completed = grat.service.years
    rule = L.get(f"compensationDaysPerYearBySeparationType.{separation_type}")
    spec = rule.value
    rules = [rule]
    band = None
    notes = []
    if spec.get("graduated"):
        bands = L.get("resignationBenefitBands")
        rules.append(bands)
        band = next((b for b in bands.value
                     if completed >= b["fromYears"] and (b["toYears"] is None or completed < b["toYears"])), None)
        days = band["daysPerYear"] if band else 0
        if band is None:
            notes.append(f"{completed} completed years is below the first band: no resignation benefit.")
        higher_of = bool(band and band.get("higherOfGratuity"))
    else:
        days = spec["days"]
        breakpoint = L.get("gratuityYearBreakpoint")
        if spec.get("daysAboveTenYears") and years > int(breakpoint.value):
            days = spec["daysAboveTenYears"]
            rules.append(breakpoint)
        higher_of = bool(spec.get("higherOfGratuity"))
    if spec.get("minimumServiceYears") and completed < spec["minimumServiceYears"]:
        days = 0
        notes.append(f"Below the minimum service of {spec['minimumServiceYears']} year(s).")
    if separation_type == SeparationTypeChoices.DEATH:
        try:
            eligibility = L.get("deathCompensationEligibilityYears")
        except UnknownRule:
            eligibility = None
        if eligibility is not None and completed < int(eligibility.value):
            days = 0
            rules.append(eligibility)
            notes.append(f"Below the {eligibility.value}-year eligibility for death compensation.")
    nil = separation_type == SeparationTypeChoices.DISMISSAL and gross_misconduct
    if nil:
        days, higher_of = 0, False
        notes.append("Nil: dismissal for theft, fraud, dishonesty, rioting, arson or wilful breach of discipline.")

    if employee.statutory.gratuity_eligible:
        gratuity_figure = grat.amount
    else:
        gratuity_figure = Figure(ZERO, "No gratuity entitlement on file (gratuityEligible is off): "
                                       "compared with nil — \"gratuity, if any\"")
    divisor = L.get("dayWageDivisor")
    base_value, base_label = wage_base(employee, structure)
    compensation = Figure(
        round_to_taka(base_value * days * years / divisor.decimal),
        f"{base_label.capitalize()} ÷ {divisor.value} × {days} days × {years} years; rounded to the taka",
        rules + [divisor], [grat.base],
    )
    if nil:
        payable_value, winner = ZERO, "NIL"
    elif higher_of:
        payable_value = max(gratuity_figure.value, compensation.value)
        winner = "GRATUITY" if gratuity_figure.value > compensation.value else "COMPENSATION"
    elif days > 0:
        payable_value, winner = compensation.value, "COMPENSATION"
    else:
        payable_value, winner = gratuity_figure.value, "GRATUITY"
    payable = Figure(
        payable_value,
        {"NIL": "Nil entitlement",
         "GRATUITY": "Gratuity" + (", the higher of the two" if higher_of else ""),
         "COMPENSATION": "Compensation" + (", the higher of the two" if higher_of else "")}[winner],
        rules, [gratuity_figure, compensation],
    )
    return {
        "type": separation_type,
        "on": on.isoformat(),
        "years": years,
        "completedYears": completed,
        "service": grat.service.as_dict(),
        "gratuityEligible": employee.statutory.gratuity_eligible,
        "daysPerYear": days,
        "graduated": bool(spec.get("graduated")),
        "band": band,
        "higherOfGratuity": higher_of,
        "gratuity": gratuity_figure.as_dict(),
        "compensation": compensation.as_dict(),
        "payable": payable.as_dict(),
        "winner": winner,
        "rule": rule.as_dict(),
        "notes": notes,
    }


def retirement_age_warning(employee, on, book):
    """Retirement before the statutory age is allowed, but worth saying."""
    from .tax import completed_years

    try:
        age_rule = book.labour.get("retirementAge")
    except UnknownRule:  # the 2015 set does not carry it
        return None
    age = completed_years(employee.dob, on)
    if age is not None and age < int(age_rule.value):
        return {
            "key": "separation.retirementBeforeAge",
            "message": f"Retiring at {age}, before the retirement age of {age_rule.value} ({age_rule.citation}).",
        }
    return None


# ----------------------------------------------------- the salary tab panel


def provident_fund(employee, structure, book):
    """Both sides of the contribution, on basic (s.264). Only for a member."""
    statutory = employee.statutory
    if not statutory.pf_member:
        return None
    rule = book.labour.get("pfEmployeeRate")

    def side(percent, who):
        if percent is None:
            return None
        return Figure(round_to_paisa(structure.basic * to_decimal(percent) / 100),
                      f"{who} {percent}% of basic {structure.basic}", [rule]).as_dict()

    return {"employee": side(statutory.pf_employee, "Employee"), "employer": side(statutory.pf_employer, "Employer")}


def derived(employee, structure, as_of, book):
    """What the structure drives (the salary tab's derivation panel): every
    figure with its basis, citation and confidence (§9)."""
    out = {
        "overtimeHourly": overtime_hourly(structure, book).as_dict(),
        "providentFund": provident_fund(employee, structure, book),
        "festivalBonus": festival_bonus(employee, structure, as_of, book),
        "leave": leave(employee, structure, book),
        "gratuity": None,
        "gratuityBreakpoint": None,
    }
    if employee.doj:
        out["gratuity"] = gratuity(employee, structure, as_of, book).as_dict()
        out["gratuityBreakpoint"] = gratuity_breakpoint(employee, structure, as_of, book)
    return out
