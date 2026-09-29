from autoslug import AutoSlugField

from django.db import models

from attendanceio.django_rest.helpers.date_times import get_time_difference

from common.models import BaseModelWithUID

from .choices import (
    DailyTimeTrackingStatusChoices,
    DailyTimeTrackingKindChoices,
    AttendanceStatusChoices,
    HolidayStatusChoices,
    HolidayDetailsTypeChoices,
    AttendanceProcessStatusChoices,
    PunchDataDailyTimeStatusChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_daily_time_tracking_slug,
    get_daily_time_tracking_session_slug,
    get_attendance_slug,
    get_holiday_slug,
    get_holiday_details_slug,
    get_attendance_process_slug,
    get_attendance_process_item_slug,
    get_punch_data_daily_time_slug,
)

from .managers import AttendanceQuerySet, HolidayQuerySet


class Attendance(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_attendance_slug, unique=True, db_index=True)
    date = models.DateField()
    check_in = models.TimeField(blank=True, null=True)
    check_out = models.TimeField(blank=True, null=True)
    status = models.CharField(
        choices=AttendanceStatusChoices,
        default=AttendanceStatusChoices.DRAFT,
        max_length=20,
    )
    worked_hour_count = models.FloatField(default=0)
    remark = models.TextField(null=True, blank=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    shift = models.ForeignKey(
        "companyio.CompanyShift", on_delete=models.SET_NULL, blank=True, null=True
    )

    # manager
    objects = AttendanceQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date", "company"],
                name="unique_attendance_record_per_employee_per_day",
            )
        ]

    def __str__(self):
        return f"ID: {self.id}, Employee: {self.employee}, Date: {self.date}"

    def get_late_hour_count(self):
        shift = self.shift
        return (
            get_time_difference(self.date, self.check_in, shift.in_time) if shift else 0
        )

    def get_ot_hour_count(self):
        shift = self.shift
        difference_count = self.worked_hour_count - shift.regular_hour if shift else 0
        return difference_count if difference_count > 0 else 0


class DailyTimeTracking(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_daily_time_tracking_slug, unique=True, db_index=True
    )
    date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=DailyTimeTrackingStatusChoices,
        default=DailyTimeTrackingStatusChoices.DRAFT,
    )
    worked_hour = models.FloatField(default=0, null=True, blank=True)
    check_in = models.TimeField(blank=True, null=True)
    check_out = models.TimeField(blank=True, null=True)
    remark = models.TextField(null=True, blank=True)
    is_tracked = models.BooleanField(default=False)

    # FK
    created_by = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    shift = models.ForeignKey("companyio.CompanyShift", on_delete=models.CASCADE)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "employee", "company"],
                name="unique_attendance_for_employee_per_day",
            )
        ]

    def __str__(self):
        return f"ID: {self.id}, Name: {self.employee.name_en}"

    def get_worked_hour_count(self):
        total_hours = self.dailytimetrackingsession_set.aggregate(
            total=models.Sum("worked_hour")
        )["total"]
        return total_hours or 0


class DailyTimeTrackingSession(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_daily_time_tracking_session_slug, unique=True, db_index=True
    )
    worked_hour = models.FloatField(blank=True, null=True)
    check_in = models.TimeField(blank=True, null=True)
    check_out = models.TimeField(blank=True, null=True)
    kind = models.CharField(
        max_length=50,
        choices=DailyTimeTrackingKindChoices,
        default=DailyTimeTrackingKindChoices.CREATED,
    )
    remark = models.TextField(null=True, blank=True)

    # FK
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    daily_time_tracking = models.ForeignKey(DailyTimeTracking, on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Name: {self.daily_time_tracking}, Worked Hours: {self.worked_hour}"


class Holiday(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_holiday_slug, unique=True, db_index=True)
    from_date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    weekend = models.TextField(
        null=True,
        blank=True,
        help_text="Help text: List of weekend days, e.g., ['Saturday', 'Sunday']",
    )
    total_holidays = models.PositiveIntegerField(default=0, null=True, blank=True)
    color = models.CharField(max_length=20, default="#FF0000", null=True, blank=True)
    status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=HolidayStatusChoices.choices,
        default=HolidayStatusChoices.ACTIVE,
    )

    # FK
    created_by = models.ForeignKey(
        "employeeio.Employee",
        related_name="holiday_set",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    objects = HolidayQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, title: {self.title}, From: {self.from_date}, To: {self.to_date}"


class HolidayDetails(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_holiday_details_slug, unique=True, db_index=True
    )
    type = models.CharField(
        max_length=50,
        choices=HolidayDetailsTypeChoices.choices,
        default=HolidayDetailsTypeChoices.HOLIDAY,
    )
    date = models.DateField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    # FK
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    holiday = models.ForeignKey(
        Holiday, on_delete=models.CASCADE, related_name="details"
    )

    def __str__(self):
        return f"ID: {self.id}, Date: {self.date}"

    class Meta:
        ordering = ["date"]


class PunchDataDailyTime(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_punch_data_daily_time_slug, unique=True, db_index=True
    )
    date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=PunchDataDailyTimeStatusChoices,
        default=PunchDataDailyTimeStatusChoices.DRAFT,
    )
    worked_hour = models.FloatField(default=0, null=True, blank=True)
    check_in = models.TimeField(blank=True, null=True)
    check_out = models.TimeField(blank=True, null=True)
    remark = models.TextField(null=True, blank=True)
    is_punch_data = models.BooleanField(default=False)

    # FK
    created_by = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)
    shift = models.ForeignKey("companyio.CompanyShift", on_delete=models.CASCADE)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "employee", "company"],
                name="unique_punch_data_daily_time_for_employee_per_day",
            )
        ]

    def __str__(self):
        return f"ID: {self.id}, Name: {self.employee.name_en}"

    def get_worked_hour_count(self):
        return self.worked_hour or 0


class AttendanceProcess(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_attendance_process_slug, unique=True, db_index=True
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        choices=AttendanceProcessStatusChoices.choices,
        default=AttendanceProcessStatusChoices.DRAFT,
        max_length=50,
    )

    # FK
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, Start Date: {self.start_date}"

    def get_last_process_date(self):
        return AttendanceProcess.objects.aggregate(models.Max("end_date"))[
            "end_date__max"
        ]


class AttendanceProcessItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_attendance_process_item_slug, unique=True, db_index=True
    )

    # Fk
    attendance_process = models.ForeignKey(AttendanceProcess, on_delete=models.CASCADE)
    attendance = models.ForeignKey(Attendance, on_delete=models.CASCADE)
    holiday = models.ForeignKey(
        Holiday, on_delete=models.SET_NULL, blank=True, null=True
    )
    leave = models.ForeignKey(
        "leaveio.LeaveRequest", on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, Attendance: {self.attendance}"
