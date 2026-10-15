"""Shared pieces: refusals, the audit, periods, the calendar and shifts.

Times: Asia/Dhaka, UTC+6, no daylight saving (§2.3). Punches are stored as
instants and read in Dhaka time; there is no DST path to build.
"""

import calendar as pycal
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q

from common import clock
from employeeio.services.salary_access import actor_role
from employeeio.services.sites import default_site
from rulebookio.book import NoRuleSetInForce, resolve
from rulebookio.choices import RuleFamilyChoices

from ..choices import CalendarStatusChoices, PeriodStatusChoices
from ..models import AttendanceAudit, AttendancePeriod, HolidayCalendar, Shift, ShiftAssignment
from .engine import HALF, HOLIDAY, WEEKLY, WORKING, ShiftSpec

DHAKA = ZoneInfo("Asia/Dhaka")
ENGINE_VERSION = "pilucent-attendance/1"


class AttendanceRefused(Exception):
    """A refused operation: `errors` is field -> messages."""

    def __init__(self, errors, status=400, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


class CalendarMissing(AttendanceRefused):
    """No published calendar: refuse rather than assume Friday (§3.7)."""

    def __init__(self, site, year):
        super().__init__({"calendar": [
            f"No published {year} holiday calendar for {site.name}. Publish one before attendance can be "
            "computed — assuming Friday is right for a factory and wrong for a shop."]}, status=409,
            detail={"calendarYear": year, "site": str(site.uid)})


def actor_name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def audit(company, action, user, *, employee=None, day=None, period=None, before=None, after=None, reason="",
          rule_set=None):
    AttendanceAudit.objects.create(
        company=company, employee=employee, business_date=day, period=period, action=action,
        actor=user if user is not None and getattr(user, "is_authenticated", False) else None,
        actor_name=actor_name(user), actor_role=actor_role(user, company), before_json=before, after_json=after,
        reason=reason or "", rule_set=rule_set or (period.rule_set if period else None),
        engine_version=ENGINE_VERSION,
    )


# ------------------------------------------------------------------- months


def month_start(d):
    return d.replace(day=1)


def month_end(d):
    return d.replace(day=pycal.monthrange(d.year, d.month)[1])


def days_of(first, last):
    out, d = [], first
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def parse_month(text):
    """'2026-10' -> date(2026, 10, 1)."""
    try:
        y, m = (int(x) for x in str(text).split("-")[:2])
        return date(y, m, 1)
    except (TypeError, ValueError):
        raise AttendanceRefused({"month": ["month must be YYYY-MM."]}) from None


def site_for(company, uid=None):
    from employeeio.models import Site

    if uid:
        found = Site.objects.filter(company=company, uid=uid).first()
        if found is None:
            raise AttendanceRefused({"site": ["No such site in this company."]}, status=404)
        return found
    return default_site(company)


def site_employees(company, site):
    from employeeio.models import Employee

    qs = Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
    qs = qs.filter(Q(site=site) | Q(site__isnull=True)) if site.is_default else qs.filter(site=site)
    return qs.select_related("department", "designation").order_by("code")


def ensure_period(company, site, month):
    """The month's period, opened on first use with the labour rule set in
    force on its first day pinned to it."""
    month = month_start(month)
    found = AttendancePeriod.objects.filter(site=site, period_month=month).select_related("rule_set").first()
    if found is not None:
        return found
    try:
        rule_set = resolve(RuleFamilyChoices.LABOUR, month)
    except NoRuleSetInForce as exc:
        raise AttendanceRefused({"month": [str(exc)]}, status=409) from None
    try:
        with transaction.atomic():
            return AttendancePeriod.objects.create(company=company, site=site, period_month=month, rule_set=rule_set)
    except IntegrityError:
        return AttendancePeriod.objects.select_related("rule_set").get(site=site, period_month=month)


def period_phase(period, today=None):
    """OPEN while punches arrive, REVIEW once the month has ended, LOCKED."""
    if period.status == PeriodStatusChoices.LOCKED:
        return PeriodStatusChoices.LOCKED
    return PeriodStatusChoices.REVIEW if month_end(period.period_month) < (today or clock.today()) \
        else PeriodStatusChoices.OPEN


def refuse_if_locked(period, what="Attendance"):
    if period.status == PeriodStatusChoices.LOCKED:
        raise AttendanceRefused({"period": [
            f"{period.period_month:%B %Y} is locked. {what} cannot change until it is reopened, with a reason."]},
            status=409)


def locked_months(site, first, last):
    return list(AttendancePeriod.objects.filter(site=site, status=PeriodStatusChoices.LOCKED,
                                                period_month__gte=month_start(first),
                                                period_month__lte=month_start(last))
                .values_list("period_month", flat=True))


# ----------------------------------------------------------------- calendar


def published_calendar(site, year):
    return (HolidayCalendar.objects.filter(site=site, calendar_year=year, status=CalendarStatusChoices.PUBLISHED)
            .prefetch_related("days").first())


class DayKinds:
    """What the calendar says each day is. `strict` refuses with no published
    calendar; otherwise a year without one reads as working days, which is
    only ever used for hour totals (§6.4), never for a status."""

    def __init__(self, site, years, strict=True):
        self.site = site
        self.calendars = {}
        self.missing = set()
        for year in years:
            cal = published_calendar(site, year)
            if cal is None:
                if strict:
                    raise CalendarMissing(site, year)
                self.missing.add(year)
            self.calendars[year] = cal

    def of(self, d):
        cal = self.calendars.get(d.year)
        if cal is None:
            return WORKING, None
        for day in cal.days.all():
            if day.holiday_date == d:
                return (HALF if day.kind == "HALF_DAY" else HOLIDAY), day.name
        weekly = (cal.weekly_pattern or {}).get(str(d.isoweekday()))
        if weekly is not None and float(weekly) >= 1:
            return WEEKLY, None
        if weekly is not None and float(weekly) > 0:
            return HALF, None
        return WORKING, None


# ------------------------------------------------------------------- shifts


def assignments_by_employee(employees, first, last):
    """{employee_id: [(from, to, ShiftSpec)]} overlapping [first, last]."""
    rows = (ShiftAssignment.objects.filter(employee__in=employees, effective_from__lte=last)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=first)).select_related("shift"))
    out = {}
    for a in rows:
        out.setdefault(a.employee_id, []).append((a.effective_from, a.effective_to, ShiftSpec.of(a.shift)))
    return out


def shift_on(windows, d):
    for start, end, spec in windows or []:
        if start <= d and (end is None or end >= d):
            return spec
    return None


def current_assignment(employee, on=None):
    on = on or clock.today()
    return (ShiftAssignment.objects.filter(employee=employee, effective_from__lte=on)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on)).select_related("shift").first())


def shifts_of(site, on=None):
    on = on or clock.today()
    return list(Shift.objects.filter(site=site, is_active=True, effective_from__lte=on)
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on)).order_by("code"))


def business_date_and_minute(punched_at, windows):
    """Which business date a punch belongs to, and its minute from that
    date's midnight (§2.2). A night shift that started yesterday and has not
    ended (allowing four hours after its end) claims a small-hours punch."""
    local = punched_at.astimezone(DHAKA)
    d = local.date()
    minute = local.hour * 60 + local.minute
    yesterday = shift_on(windows, d - timedelta(days=1))
    if yesterday is not None and yesterday.end_min > 1439 and minute <= yesterday.end_min - 1440 + 240:
        return d - timedelta(days=1), minute + 1440
    return d, minute
