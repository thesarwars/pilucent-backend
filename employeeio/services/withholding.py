"""Withholding deadlines (doc §7.6), from the tax rule set in force.

* Deposit within 2 weeks of month end, July to May; the same day for tax
  deducted on 30 June.
* Late deposit: 2% a month, capped at 24 months (s.143); the defaulter is an
  assessee-in-default, personally liable for the tax.
* Quarterly returns 25 Oct / 25 Jan / 25 Apr / 25 Jul (s.177).
* Under-deduction disallows the salary expense plus 50% (s.55).
"""

from datetime import date, timedelta

from common.money import ZERO, round_to_taka, to_decimal

from .periods import month_end, month_start, period_label
from .profile import service_parts
from .tax import Figure

JUNE = 6


def deposit_due(period, book):
    """The last day to deposit tax deducted in `period`."""
    rules = book.tax
    if period.month == JUNE and rules.value("withholding.juneDepositSameDay"):
        return month_end(period)
    return month_end(period) + timedelta(days=int(rules.value("withholding.depositDaysAfterMonthEnd")))


def months_late(due, deposited_on):
    """Whole months past the due date, a started month counting as one."""
    if deposited_on <= due:
        return 0
    parts = service_parts(due, deposited_on)
    return parts.total_months + (1 if parts.residual_days > 0 else 0)


def late_deposit_charge(amount, due, deposited_on, book):
    rate = book.tax.get("withholding.lateDepositMonthlyRate")
    cap = book.tax.get("withholding.lateDepositCapMonths")
    late = months_late(due, deposited_on)
    months = min(late, int(cap.value))
    return Figure(
        round_to_taka(to_decimal(amount) * rate.decimal * months) if months else ZERO,
        f"{rate.value} × {months} month(s) late (a started month counts; at most {cap.value}) "
        "× the tax deposited late; rounded to the taka",
        [rate, cap],
    )


def next_quarterly_return(as_of, book):
    """The next quarterly withholding return due on or after `as_of`."""
    rule = book.tax.get("withholding.quarterlyReturnDates")
    candidates = []
    for row in rule.value:
        due_month, due_day = (int(x) for x in row["due"].split("-"))
        end_month, end_day = (int(x) for x in row["quarterEnds"].split("-"))
        for year in (as_of.year, as_of.year + 1):
            due = date(year, due_month, due_day)
            # A quarter ending in a later month than its return is last year's.
            quarter_end = date(year if end_month < due_month else year - 1, end_month, end_day)
            candidates.append((due, quarter_end))
    due, quarter_end = min(c for c in candidates if c[0] >= as_of)
    return {"quarterEnds": quarter_end.isoformat(), "due": due.isoformat(),
            "citation": rule.citation, "confidence": rule.confidence}


def deadlines(as_of, book):
    """The deadlines that apply to this month's deduction."""
    period = month_start(as_of)
    due = deposit_due(period, book)
    rate = book.tax.get("withholding.lateDepositMonthlyRate")
    cap = book.tax.get("withholding.lateDepositCapMonths")
    disallow = book.tax.get("withholding.underDeductionDisallowanceRate")
    deposit_rules = [book.tax.get("withholding.depositDaysAfterMonthEnd"),
                     book.tax.get("withholding.juneDepositSameDay")]
    return {
        "period": period_label(period),
        "depositDue": Figure(
            due.isoformat(),
            "30 June: the same day" if period.month == JUNE else
            f"{deposit_rules[0].value} days after the end of {period_label(period)}",
            deposit_rules,
        ).as_dict(money=False),
        "lateDeposit": Figure(
            rate.value, f"{rate.value} a month on the late tax, capped at {cap.value} months; "
            "the defaulter is personally liable for the tax", [rate, cap],
        ).as_dict(money=False),
        "quarterlyReturn": next_quarterly_return(as_of, book),
        "underDeduction": Figure(
            disallow.value, f"Under-deduction disallows the salary expense plus {disallow.value} of it",
            [disallow],
        ).as_dict(money=False),
    }
