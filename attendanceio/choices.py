from django.db import models


class AttendanceKindChoices(models.TextChoices):
    OVERTIME = "OVERTIME", "Overtime"
    HOLIDAY = "HOLIDAY", "Holiday"


class AttendanceStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PRESENT = "PRESENT", "Present"
    ABSENT = "ABSENT", "Absent"
    LEAVE = "LEAVE", "Leave"
    LATE_ARRIVAL = "LATE_ARRIVAL", "Late Arraival"
    EARLY_DEPARTURE = "EARLY_DEPARTURE", "Early Departure"
    HALF_DAY = "HALF_DAY", "Half Day"
    REMOVED = "REMOVED", "Removed"
    SPECIAL = "SPECIAL", "Special"
    WEEKEND = "WEEKEND", "Weekend"
    HOLIDAY = "HOLIDAY", "Holiday"


class DailyTimeTrackingStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PRESENT = "PRESENT", "Present"
    ABSENT = "ABSENT", "Absent"
    LEAVE = "LEAVE", "Leave"
    LATE_ARRIVAL = "LATE_ARRIVAL", "Late Arraival"
    EARLY_DEPARTURE = "EARLY_DEPARTURE", "Early Departure"
    OVERTIME = "OVERTIME", "Overtime"
    HOLIDAY = "HOLIDAY", "Holiday"
    REMOVED = "REMOVED", "Removed"


class DailyTimeTrackingKindChoices(models.TextChoices):
    CREATED = "CREATED", "Created"
    UPDATED = "UPDATED", "Updated"


class HolidayStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    REMOVED = "REMOVED", "Removed"


class HolidayDetailsTypeChoices(models.TextChoices):
    HOLIDAY = "HOLIDAY", "Holiday"
    SPECIAL = "SPECIAL", "Special"
    WEEKEND = "WEEKEND", "Weekend"


class AttendanceProcessStatusChoices(models.TextChoices):
    COMPLETED = "COMPLETED", "Completed"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    CLOSED = "CLOSED", "Closed"
    CANCELED = "CANCELED", "Canceled"
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"


class PunchDataDailyTimeStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PRESENT = "PRESENT", "Present"
    ABSENT = "ABSENT", "Absent"
    LEAVE = "LEAVE", "Leave"
    LATE_ARRIVAL = "LATE_ARRIVAL", "Late Arraival"
    EARLY_DEPARTURE = "EARLY_DEPARTURE", "Early Departure"
    OVERTIME = "OVERTIME", "Overtime"
    HOLIDAY = "HOLIDAY", "Holiday"
    REMOVED = "REMOVED", "Removed"
