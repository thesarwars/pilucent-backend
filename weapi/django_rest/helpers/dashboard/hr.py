"""Reusable HR / attendance / payroll aggregations for v2 dashboard cards.

Employees have no direct company FK; they are scoped through
``company.get_employees()`` (user -> companyuser -> company). Payroll runs are
scoped the same way via the employee relation.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Q, Sum, Count, DecimalField, F, Min
from django.db.models.functions import Coalesce

from employeeio.models import Employee
from employeeio.choices import EmployeeStatusChoices

from attendanceio.models import Attendance
from attendanceio.choices import AttendanceStatusChoices

from leaveio.models import LeaveRequest
from leaveio.choices import EmployeeLeaveRequestStatusChoices

from payrollio.models import (
    PayrollSalaryProcess,
    PaySchedule,
    PayrollSalaryComponent,
)
from payrollio.choicess import (
    PayrollSalaryProcessStatusChoices,
    PayrollComponentCategoryChoice,
    PayTypeChoice,
)


ZERO = Decimal("0.00")
DEFAULT_EVENT_WINDOW_DAYS = 30


def company_employees(company):
    return company.get_employees()


def active_employees(company):
    return company_employees(company).filter(status=EmployeeStatusChoices.ACTIVE)


# ---------------------------------------------------------------------------
# Employee Overview
# ---------------------------------------------------------------------------

def employee_overview(company, date_from, date_to):
    employees = company_employees(company)
    active = employees.filter(status=EmployeeStatusChoices.ACTIVE)
    today = date.today()
    window_end = today + timedelta(days=DEFAULT_EVENT_WINDOW_DAYS)

    department_split = list(
        active.values("department__title").annotate(count=Count("id")).order_by("-count")
    )
    status_split = list(
        employees.values("status").annotate(count=Count("id")).order_by("-count")
    )

    return {
        "total_active": active.count(),
        "new_joiners": active.filter(doj__range=[date_from, date_to]).count(),
        "upcoming_confirmations": pending_confirmations(active, today, window_end).count(),
        "department_split": [
            {"department": row["department__title"] or "Unassigned", "count": row["count"]}
            for row in department_split
        ],
        "status_split": [
            {"status": row["status"], "count": row["count"]} for row in status_split
        ],
    }


def employee_stats(company, today=None):
    """Headcount stat-card numbers.

    ``net_change`` approximates net growth as joiners (by ``doj``) within the
    last 30 days. Separations are not subtracted yet, although the BD employee
    now date-stamps them (``separated_on``) -- a known limitation.
    """
    today = today or date.today()
    active = company_employees(company).filter(status=EmployeeStatusChoices.ACTIVE)

    month_start = today.replace(day=1)
    last_30 = today - timedelta(days=30)
    window_end = today + timedelta(days=DEFAULT_EVENT_WINDOW_DAYS)

    return {
        "total_active": active.count(),
        # The BD employee has a real date of joining (doj); the US model used
        # its confirmation date as a stand-in for one.
        "joiners_this_month": active.filter(doj__gte=month_start, doj__lte=today).count(),
        "net_change": active.filter(doj__gt=last_30, doj__lte=today).count(),
        "upcoming_confirmations": pending_confirmations(active, today, window_end).count(),
    }


def pending_confirmations(employees, today, window_end):
    """Probationers not yet confirmed whose probation ends in the window.

    Not a future `confirmation` date: the BD contract treats one as a data
    error that blocks payroll (docs/employee-profile.md §2.2, §3.1).
    """
    return employees.filter(
        confirmation__isnull=True,
        separated_on__isnull=True,  # a separated probationer is never confirmed
        probation_end__gt=today,
        probation_end__lte=window_end,
    )


# ---------------------------------------------------------------------------
# Attendance Summary / Today's Workforce
# ---------------------------------------------------------------------------

def _is_late(attendance):
    """Late = check-in later than shift start + grace period.

    ``CompanyShift.grace_time`` is stored in minutes but unused in the legacy
    status logic; we apply it here for dashboard accuracy.
    """
    shift = attendance.shift
    if shift is None or attendance.check_in is None or shift.in_time is None:
        return attendance.status == AttendanceStatusChoices.LATE_ARRIVAL
    grace = shift.grace_time or 0
    allowed = (
        datetime.combine(date.today(), shift.in_time) + timedelta(minutes=grace)
    ).time()
    return attendance.check_in > allowed


def attendance_summary(company, day=None):
    day = day or date.today()
    scheduled = active_employees(company)
    scheduled_count = scheduled.count()

    attendances = list(
        Attendance.objects.filter(company=company, date=day).select_related("shift")
    )
    present = [
        a
        for a in attendances
        if a.status in (AttendanceStatusChoices.PRESENT, AttendanceStatusChoices.LATE_ARRIVAL)
        or a.check_in is not None
    ]
    late = [a for a in present if _is_late(a)]

    on_leave = leave_today_count(company, day)

    present_count = len(present)
    rate = round((present_count / scheduled_count * 100), 1) if scheduled_count else 0

    return {
        "scheduled": scheduled_count,
        "present": present_count,
        "late": len(late),
        "on_leave": on_leave,
        "attendance_rate": rate,
    }


def leave_today_count(company, day=None):
    day = day or date.today()
    return (
        LeaveRequest.objects.filter(
            company=company,
            status=EmployeeLeaveRequestStatusChoices.APPROVED,
            from_date__lte=day,
            to_date__gte=day,
        )
        .values("employee_id")
        .distinct()
        .count()
    )


def todays_workforce(company, day=None):
    """Approximate workforce status for today.

    There is no per-day roster model, so "scheduled" is approximated as active
    employees who have a shift assigned.
    """
    day = day or date.today()
    scheduled = active_employees(company)
    scheduled_with_shift = scheduled.filter(shift__isnull=False)
    scheduled_count = scheduled_with_shift.count() or scheduled.count()

    attendances = list(
        Attendance.objects.filter(company=company, date=day).select_related("shift")
    )
    checked_in_ids = {a.employee_id for a in attendances if a.check_in is not None}
    on_shift = [
        a for a in attendances if a.check_in is not None and a.check_out is None
    ]
    on_leave = leave_today_count(company, day)
    absent = [
        a for a in attendances if a.status == AttendanceStatusChoices.ABSENT
    ]

    yet_to_check_in = max(scheduled_count - len(checked_in_ids) - on_leave, 0)

    return {
        "scheduled": scheduled_count,
        "on_shift": len(on_shift),
        "yet_to_check_in": yet_to_check_in,
        "on_leave": on_leave,
        "absent": len(absent),
    }


# ---------------------------------------------------------------------------
# Leave Requests
# ---------------------------------------------------------------------------

def leave_request_counts(company):
    qs = LeaveRequest.objects.filter(company=company)
    rows = qs.values("status").annotate(count=Count("id"))
    counts = {row["status"]: row["count"] for row in rows}
    return {
        "pending": counts.get(EmployeeLeaveRequestStatusChoices.PENDING, 0),
        "approved": counts.get(EmployeeLeaveRequestStatusChoices.APPROVED, 0),
        "rejected": counts.get(EmployeeLeaveRequestStatusChoices.REJECTED, 0),
    }


def pending_leave_requests(company, limit=5):
    return (
        LeaveRequest.objects.filter(
            company=company,
            status=EmployeeLeaveRequestStatusChoices.PENDING,
        )
        .select_related("employee", "leave_type")
        .order_by("from_date")[:limit]
    )


# ---------------------------------------------------------------------------
# Payroll Snapshot
# ---------------------------------------------------------------------------

def payroll_runs_qs(company):
    user_ids = company.companyuser_set.values_list("user_id", flat=True)
    return PayrollSalaryProcess.objects.filter(employee__user__id__in=user_ids)


def payroll_snapshot(company, date_from, date_to):
    qs = payroll_runs_qs(company).filter(
        status=PayrollSalaryProcessStatusChoices.FINALIZED,
        pay_date__range=[date_from, date_to],
    )
    agg = qs.aggregate(
        gross=Coalesce(Sum("gross_pay"), ZERO, output_field=DecimalField()),
        net=Coalesce(Sum("net_pay"), ZERO, output_field=DecimalField()),
        employee_taxes=Coalesce(
            Sum("employee_taxes_deductions"), ZERO, output_field=DecimalField()
        ),
        employer_taxes=Coalesce(
            Sum("employer_taxes_contributions"), ZERO, output_field=DecimalField()
        ),
        employees_paid=Count("employee", distinct=True),
    )
    total_cost = agg["gross"] + agg["employer_taxes"]
    return {
        "total_cost": float(total_cost),
        "gross": float(agg["gross"]),
        "net": float(agg["net"]),
        "employee_taxes_deductions": float(agg["employee_taxes"]),
        "employer_taxes_contributions": float(agg["employer_taxes"]),
        "employees_paid": agg["employees_paid"],
    }


def payroll_due(company, today=None):
    """Upcoming payroll obligation.

    Amount = total employer cost (gross + employer contributions) of DRAFT runs
    scheduled on/after today; due date = earliest such pay date, falling back to
    the company's next scheduled pay date when no draft runs exist yet.
    """
    today = today or date.today()
    drafts = payroll_runs_qs(company).filter(
        status=PayrollSalaryProcessStatusChoices.DRAFT,
        pay_date__gte=today,
    )
    agg = drafts.aggregate(
        amount=Coalesce(
            Sum(F("gross_pay") + F("employer_taxes_contributions")),
            ZERO,
            output_field=DecimalField(),
        ),
        next_date=Min("pay_date"),
    )
    due_date = agg["next_date"]
    if due_date is None:
        due_date = (
            PaySchedule.objects.filter(
                company=company, next_pay_date__gte=today
            ).aggregate(d=Min("next_pay_date"))["d"]
        )
    days_until = (due_date - today).days if due_date else None
    return {
        "amount": float(agg["amount"]),
        "due_date": due_date,
        "days_until": days_until,
    }


def attendance_rate(company, day=None):
    return attendance_summary(company, day=day)["attendance_rate"]


def attendance_rate_with_trend(company, day=None):
    """Today's attendance rate plus yesterday's for a day-over-day trend."""
    day = day or date.today()
    current = attendance_rate(company, day=day)
    previous = attendance_rate(company, day=day - timedelta(days=1))
    return current, previous


def attendance_rate_average(company, day=None, days=7):
    """Average attendance rate over the ``days`` days before ``day``.

    Computed in a single grouped query (present counts per day) instead of
    re-running :func:`attendance_summary` once per day. The denominator is the
    current active headcount, matching :func:`attendance_rate`.
    """
    day = day or date.today()
    if days <= 0:
        return 0

    start = day - timedelta(days=days)
    end = day - timedelta(days=1)

    scheduled_count = active_employees(company).count()
    if not scheduled_count:
        return 0

    present_rows = (
        Attendance.objects.filter(company=company, date__range=[start, end])
        .values("date")
        .annotate(
            present=Count(
                "id",
                filter=Q(
                    status__in=(
                        AttendanceStatusChoices.PRESENT,
                        AttendanceStatusChoices.LATE_ARRIVAL,
                    )
                )
                | Q(check_in__isnull=False),
            )
        )
    )
    present_by_date = {row["date"]: row["present"] for row in present_rows}

    total_rate = 0.0
    for offset in range(1, days + 1):
        present = present_by_date.get(day - timedelta(days=offset), 0)
        total_rate += present / scheduled_count * 100
    return round(total_rate / days, 1)


def payroll_breakdown(company, date_from, date_to):
    """Component-level payroll breakdown for FINALIZED runs in the period.

    Splits pay components into base salary vs allowances (overtime/bonus/etc.)
    and surfaces employee deductions and employee taxes, plus net pay.
    """
    runs = payroll_runs_qs(company).filter(
        status=PayrollSalaryProcessStatusChoices.FINALIZED,
        pay_date__range=[date_from, date_to],
    )
    net = runs.aggregate(
        net=Coalesce(Sum("net_pay"), ZERO, output_field=DecimalField())
    )["net"]

    components = PayrollSalaryComponent.objects.filter(payroll__in=runs)
    agg = components.aggregate(
        gross_salary=Coalesce(
            Sum(
                "current",
                filter=Q(payroll_category=PayrollComponentCategoryChoice.PAY)
                & Q(payroll_type=PayTypeChoice.REGULAR),
            ),
            ZERO,
            output_field=DecimalField(),
        ),
        allowances=Coalesce(
            Sum(
                "current",
                filter=Q(payroll_category=PayrollComponentCategoryChoice.PAY)
                & ~Q(payroll_type=PayTypeChoice.REGULAR),
            ),
            ZERO,
            output_field=DecimalField(),
        ),
        deductions=Coalesce(
            Sum(
                "current",
                filter=Q(
                    payroll_category=PayrollComponentCategoryChoice.EMPLOYEE_DEDUCTIONS
                ),
            ),
            ZERO,
            output_field=DecimalField(),
        ),
        taxes=Coalesce(
            Sum(
                "current",
                filter=Q(
                    payroll_category=PayrollComponentCategoryChoice.EMPLOYEE_TAXES
                ),
            ),
            ZERO,
            output_field=DecimalField(),
        ),
    )
    return {
        "gross_salary": float(agg["gross_salary"]),
        "allowances": float(agg["allowances"]),
        "deductions": float(agg["deductions"]),
        "taxes": float(agg["taxes"]),
        "net": float(net),
    }


# ---------------------------------------------------------------------------
# Upcoming Events
# ---------------------------------------------------------------------------

def upcoming_events(company, days=DEFAULT_EVENT_WINDOW_DAYS):
    today = date.today()
    window_end = today + timedelta(days=days)
    employees = active_employees(company).select_related("department", "user")

    events = []

    for emp in employees:
        name = emp.name_en or (emp.user.name if emp.user_id and emp.user else None)
        # Birthdays (month/day match within window)
        if emp.dob and _date_in_window(emp.dob, today, window_end):
            events.append(
                {
                    "type": "birthday",
                    "employee_uid": str(emp.uid),
                    "name": name,
                    "date": _next_anniversary(emp.dob, today).isoformat(),
                }
            )
        # Work anniversaries, from the date of joining -- a whole year at least,
        # so a joining date inside the window is not its own anniversary.
        if emp.doj:
            anniversary = _next_anniversary(emp.doj, today)
            if anniversary.year > emp.doj.year and anniversary <= window_end:
                events.append(
                    {
                        "type": "work_anniversary",
                        "employee_uid": str(emp.uid),
                        "name": name,
                        "date": anniversary.isoformat(),
                    }
                )
        # Contract end dates (absolute date in window)
        if emp.contract_end and today <= emp.contract_end <= window_end:
            events.append(
                {
                    "type": "contract_end",
                    "employee_uid": str(emp.uid),
                    "name": name,
                    "date": emp.contract_end.isoformat(),
                }
            )

    events.sort(key=lambda e: e["date"])
    return events


def _next_anniversary(d, today):
    try:
        candidate = d.replace(year=today.year)
    except ValueError:
        # Feb 29 -> use Feb 28 in non-leap years
        candidate = d.replace(year=today.year, day=28)
    if candidate < today:
        try:
            candidate = d.replace(year=today.year + 1)
        except ValueError:
            candidate = d.replace(year=today.year + 1, day=28)
    return candidate


def _date_in_window(d, today, window_end):
    return today <= _next_anniversary(d, today) <= window_end
