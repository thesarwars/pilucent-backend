"""Per-employee/per-date context resolution.

Resolves the *expected* day for an employee using the same precedence as the
daily attendance process — Holiday/Weekend/Special -> approved Leave -> normal
working day — but batched so a whole team can be resolved for one date in a
couple of queries. Returned context statuses feed the pure derivation service
(to infer unmarked rows and to flag ``needs_review``).
"""

from attendanceio.choices import AttendanceStatusChoices
from attendanceio.models import HolidayDetails

from leaveio.choices import EmployeeLeaveRequestStatusChoices
from leaveio.models import LeaveRequest


def resolve_context_for_date(employees, date):
    """Return ``{employee_id: context_status or None}`` for a single ``date``.

    ``context_status`` is one of the holiday-family statuses (HOLIDAY / WEEKEND
    / SPECIAL) or LEAVE, or ``None`` for an ordinary working day.
    """
    employees = list(employees)
    if not employees:
        return {}

    holiday_ids = {emp.holiday_id for emp in employees if emp.holiday_id}
    detail_type_by_holiday = {}
    if holiday_ids:
        for detail in HolidayDetails.objects.filter(
            holiday_id__in=holiday_ids, date=date
        ).values("holiday_id", "type"):
            # First matching detail per holiday wins (HolidayDetails is ordered
            # by date; one row per date is the norm).
            detail_type_by_holiday.setdefault(detail["holiday_id"], detail["type"])

    employee_ids = [emp.id for emp in employees]
    employees_on_leave = set(
        LeaveRequest.objects.filter(
            employee_id__in=employee_ids,
            status=EmployeeLeaveRequestStatusChoices.APPROVED,
            from_date__lte=date,
            to_date__gte=date,
        ).values_list("employee_id", flat=True)
    )

    resolved = {}
    for emp in employees:
        if emp.holiday_id and emp.holiday_id in detail_type_by_holiday:
            resolved[emp.id] = detail_type_by_holiday[emp.holiday_id]
        elif emp.id in employees_on_leave:
            resolved[emp.id] = AttendanceStatusChoices.LEAVE
        else:
            resolved[emp.id] = None
    return resolved
