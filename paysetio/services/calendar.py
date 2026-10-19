"""Working days from the establishment's own calendar (§1.8, §4.5).

Never `weekday not in (5, 6)`: a factory on a single weekly holiday works
Saturdays, and every deadline computed on a two-day weekend is two days
early. A working day is one the site's PUBLISHED holiday calendar does not
mark as a weekly or a festival/public holiday; a half day is a working day.
A year without a published calendar refuses (`CalendarMissing`), as the
attendance engine does.
"""

from calendar import monthrange
from datetime import date, timedelta

from timekeepingio.services.base import HALF, WORKING, CalendarMissing, DayKinds

S123_WORKING_DAYS = 7  # Bangladesh Labour Act 2006, s.123: the seventh working day


class Calendar:
    """Day kinds for a site across years, loaded on demand."""

    def __init__(self, site):
        self.site = site
        self._kinds = {}

    def _year(self, year):
        if year not in self._kinds:
            self._kinds[year] = DayKinds(self.site, [year], strict=True)
        return self._kinds[year]

    def working(self, d):
        kind, _ = self._year(d.year).of(d)
        return kind in (WORKING, HALF)

    def has_year(self, year):
        try:
            self._year(year)
            return True
        except CalendarMissing:
            return False

    def add_working_days(self, start, n):
        d, added = start, 0
        while added < n:
            d += timedelta(days=1)
            if self.working(d):
                added += 1
        return d

    def working_days(self, first, last):
        n, d = 0, first
        while d <= last:
            if self.working(d):
                n += 1
            d += timedelta(days=1)
        return n


def month_bounds(month):
    first = date(month.year, month.month, 1)
    return first, date(month.year, month.month, monthrange(month.year, month.month)[1])


def statutory_deadline(cal, period_end):
    """s.123: wages are paid before the end of the seventh working day after
    the last day of the wage period."""
    return cal.add_working_days(period_end, S123_WORKING_DAYS)


def payment_date(month, payment_day):
    """The payment for wage month `month` falls on `payment_day` of the next
    month, clipped to its length."""
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return nxt.replace(day=min(int(payment_day), monthrange(nxt.year, nxt.month)[1]))


def check_payment_day(cal, payment_day, months):
    """[{month, wagePeriodEnd, deadline, paymentDate, late}] for each month
    whose calendar years are published, and the months that could not be
    checked. The wage period is the calendar month: the cut-off is when
    attendance and inputs close inside it, not where the period ends."""
    checked, unchecked = [], []
    for m in months:
        _, end = month_bounds(m)
        try:
            deadline = statutory_deadline(cal, end)
        except CalendarMissing:
            unchecked.append(m.strftime("%Y-%m"))
            continue
        pay = payment_date(m, payment_day)
        checked.append({"month": m.strftime("%Y-%m"), "wagePeriodEnd": end.isoformat(),
                        "deadline": deadline.isoformat(), "paymentDate": pay.isoformat(), "late": pay > deadline})
    return checked, unchecked
