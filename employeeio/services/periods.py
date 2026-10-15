"""Payroll periods: calendar months, and which of them the company has
processed (`ProcessedPayrollPeriod`).

A period is named by its first day. A backdated change reopens every
processed period that ends on or after its effective date (doc §5.2, §6.2).
"""

import calendar

from common import clock

from .profile import add_months


def month_start(on):
    return on.replace(day=1)


def month_end(on):
    return on.replace(day=calendar.monthrange(on.year, on.month)[1])


def days_in_month(on):
    return calendar.monthrange(on.year, on.month)[1]


def period_label(period):
    """`YYYY-MM`, built from the date, never through a number formatter (§4.5)."""
    return f"{period.year:04d}-{period.month:02d}"


def processed_periods(company):
    from ..models import ProcessedPayrollPeriod

    return ProcessedPayrollPeriod.objects.filter(company=company)


def next_unprocessed_period(company, today=None):
    """The first day of the month after the last processed period; with
    nothing processed yet, the first day of the current month."""
    latest = processed_periods(company).order_by("-period").values_list("period", flat=True).first()
    if latest is None:
        return month_start(today or clock.today())
    return add_months(latest, 1)


def reopened_periods(employee, effective_from):
    """Processed periods a change effective `effective_from` reaches back into:
    those ending on or after it, within the employee's service."""
    periods = processed_periods(employee.company).filter(period__gte=month_start(effective_from))
    if employee.doj:
        periods = periods.filter(period__gte=month_start(employee.doj))
    if employee.separated_on:
        periods = periods.filter(period__lte=employee.separated_on)
    return list(periods.order_by("period").values_list("period", flat=True))


def completed_runs(employee):
    """Processed periods the employee was in: within their service, and with
    a salary structure in force for some part of the period -- without one a
    record is blocked from the run (§3.1)."""
    windows = list(employee.salary_structures.live().values_list("effective_from", "effective_to"))
    if not windows:
        return 0
    count = 0
    for period in processed_periods(employee.company).values_list("period", flat=True):
        end = month_end(period)
        if employee.doj and end < employee.doj:
            continue
        if employee.separated_on and period > employee.separated_on:
            continue
        if any(start <= end and (stop is None or stop >= period) for start, stop in windows):
            count += 1
    return count
