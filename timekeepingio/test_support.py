"""Builders for the attendance tests. Nothing here is imported by production code."""

from datetime import date, datetime

from django.contrib.auth.models import Permission

from employeeio.services.sites import default_site

from .models import HolidayCalendar, HolidayCalendarDay, Punch, Shift, ShiftAssignment
from .services.base import DHAKA

FRIDAY = {"5": 1}


def day_shift(company, site=None, **fields):
    """08:00-17:00, a 60-minute unpaid break, 480 standard, 10 minutes' grace."""
    values = dict(code="A", label="General", start_min=480, end_min=1020, standard_minutes=480,
                  unpaid_break_minutes=60, late_grace_minutes=10, requires_pre_approval=True,
                  effective_from=date(2025, 1, 1))
    values.update(fields)
    return Shift.objects.create(company=company, site=site or default_site(company), **values)


def night_shift(company, site=None):
    """22:00 to 06:00 next day: 480 span, 60 break, 420 standard."""
    return day_shift(company, site, code="N", label="Night", start_min=1320, end_min=1800, standard_minutes=420,
                     is_night_shift=True)


def assign(employee, shift, effective_from=date(2025, 1, 1)):
    return ShiftAssignment.objects.create(company=employee.company, employee=employee, shift=shift,
                                          effective_from=effective_from)


def publish(company, year, pattern=None, days=(), site=None):
    """A published calendar: Friday weekly by default, plus (date, name, kind) days."""
    cal = HolidayCalendar.objects.create(company=company, site=site or default_site(company), calendar_year=year,
                                         weekly_pattern=FRIDAY if pattern is None else pattern,
                                         status="PUBLISHED")
    for when, name, kind in days:
        HolidayCalendarDay.objects.create(calendar=cal, holiday_date=when, name=name, kind=kind)
    return cal


def at(text):
    """'2027-02-01 08:00' in Dhaka time."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=DHAKA)


def punch(employee, text, direction, business_date=None):
    when = at(text)
    return Punch.objects.create(company=employee.company, employee=employee, site=default_site(employee.company),
                                punched_at=when, business_date=business_date or when.date(), direction=direction,
                                source="MANUAL")


def worked_day(employee, day, start="08:00", end="17:00"):
    punch(employee, f"{day} {start}", "IN")
    punch(employee, f"{day} {end}", "OUT")


def give_attendance_permissions(user, company, *codenames):
    from adminio.models import CompanyRole
    from companyio.models import CompanyUser

    role, _ = CompanyRole.objects.get_or_create(company=company, name="Attendance officer " + "-".join(codenames))
    role.permission.add(*Permission.objects.filter(content_type__app_label="timekeepingio", codename__in=codenames))
    CompanyUser.objects.get(user=user, company=company).roles.add(role)
    return role
