"""Profile helpers: the business key and length of service."""

import calendar
import re
from dataclasses import dataclass
from datetime import date

CODE_PREFIX = "EMP-"
CODE_DIGITS = 4
_CODE = re.compile(r"^EMP-(\d+)$")


def next_code(company):
    """The next unused `EMP-0000` code in the company. Codes are never reused,
    so this counts past the highest ever issued, not the number of rows."""
    from ..models import Employee

    highest = 0
    for code in Employee.objects.filter(company=company, code__startswith=CODE_PREFIX).values_list("code", flat=True):
        match = _CODE.match(code)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{CODE_PREFIX}{highest + 1:0{CODE_DIGITS}d}"


def add_months(start, months):
    """`start` moved by whole months, clamped to the end of a shorter month
    (31 Jan + 1 month = 28/29 Feb), so an anniversary never lands past the
    month it belongs to."""
    total = start.month - 1 + months
    year, month = start.year + total // 12, total % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class ServiceParts:
    total_months: int
    years: int
    residual_months: int
    residual_days: int

    def as_dict(self):
        return {
            "totalMonths": self.total_months,
            "years": self.years,
            "months": self.residual_months,
            "days": self.residual_days,
        }


def service_parts(joined, until):
    """Completed months of service plus the residual days, to the day.

    Ported from `calc.js serviceParts` (DEF-06 needs day precision: 6y 6m 20d
    must be distinguishable from 6y 6m). One difference: a month-end joining
    date clamps instead of overflowing into the next month.
    """
    months = (until.year - joined.year) * 12 + (until.month - joined.month)
    anchor = add_months(joined, months)
    if anchor > until:
        months -= 1
        anchor = add_months(joined, months)
    if months < 0:
        return ServiceParts(0, 0, 0, 0)
    return ServiceParts(months, months // 12, months % 12, max(0, (until - anchor).days))
