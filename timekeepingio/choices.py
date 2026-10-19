from django.db import models


class PunchDirectionChoices(models.TextChoices):
    IN = "IN", "In"
    OUT = "OUT", "Out"


class PunchSourceChoices(models.TextChoices):
    DEVICE = "DEVICE", "Device"
    MOBILE = "MOBILE", "Mobile"
    MANUAL = "MANUAL", "Manual"
    IMPORT = "IMPORT", "Import"


class DayStatusChoices(models.TextChoices):
    """§4. Only six are settable by an operator; HOLIDAY and WEEKLY_HOLIDAY
    come from the published calendar, PRESENT_OT and EXCEPTION are derived."""

    PRESENT = "PRESENT", "Present"
    PRESENT_OT = "PRESENT_OT", "Present with overtime"
    ABSENT = "ABSENT", "Absent"
    HALF_DAY = "HALF_DAY", "Half day"
    ON_LEAVE = "ON_LEAVE", "On leave"
    LEAVE_WITHOUT_PAY = "LEAVE_WITHOUT_PAY", "Leave without pay"
    HOLIDAY = "HOLIDAY", "Festival or public holiday"
    WEEKLY_HOLIDAY = "WEEKLY_HOLIDAY", "Weekly holiday"
    ON_DUTY = "ON_DUTY", "On duty"
    EXCEPTION = "EXCEPTION", "Unresolved exception"


SETTABLE_STATUSES = ("PRESENT", "ABSENT", "HALF_DAY", "ON_LEAVE", "LEAVE_WITHOUT_PAY", "ON_DUTY")


class ExceptionKindChoices(models.TextChoices):
    MISSING_OUT_PUNCH = "MISSING_OUT_PUNCH", "Missing out-punch"
    # Beyond the spec's eight: an OUT with no IN is the same gap from the
    # other end, and calling it a missing out-punch would misdescribe it.
    MISSING_IN_PUNCH = "MISSING_IN_PUNCH", "Missing in-punch"
    NO_PUNCH_ROSTERED = "NO_PUNCH_ROSTERED", "No punches but rostered"
    ABSENT_NO_LEAVE = "ABSENT_NO_LEAVE", "Absent without leave application"
    DAILY_LIMIT_EXCEEDED = "DAILY_LIMIT_EXCEEDED", "Daily hours above the statutory maximum"
    LATE_ARRIVAL = "LATE_ARRIVAL", "Late beyond grace"
    OT_UNAPPROVED = "OT_UNAPPROVED", "Overtime without pre-approval"
    WORKED_WEEKLY_HOLIDAY = "WORKED_WEEKLY_HOLIDAY", "Worked on weekly holiday"
    WORKED_FESTIVAL_HOLIDAY = "WORKED_FESTIVAL_HOLIDAY", "Worked on festival holiday"


class ExceptionStateChoices(models.TextChoices):
    OPEN = "OPEN", "Open"
    RESOLVED = "RESOLVED", "Resolved"
    # The fact stands -- a statutory breach is recorded, never resolved away.
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"


class PeriodStatusChoices(models.TextChoices):
    """Stored: OPEN or LOCKED. REVIEW is derived -- an open month that has
    ended -- so it cannot go stale."""

    OPEN = "OPEN", "Open"
    REVIEW = "REVIEW", "Review"
    LOCKED = "LOCKED", "Locked"


class CalendarStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"


class CalendarDayKindChoices(models.TextChoices):
    FESTIVAL_HOLIDAY = "FESTIVAL_HOLIDAY", "Festival holiday"
    PUBLIC_HOLIDAY = "PUBLIC_HOLIDAY", "Public holiday"
    HALF_DAY = "HALF_DAY", "Half day"


class CreditKindChoices(models.TextChoices):
    COMPENSATORY = "COMPENSATORY", "Compensatory holiday"
    SUBSTITUTE = "SUBSTITUTE", "Substitute holiday"


class PeriodStageChoices(models.TextChoices):
    """Attendance intake §6: OPEN -> PROCESSING -> REVIEW, then the lock."""

    OPEN = "OPEN", "Open"
    PROCESSING = "PROCESSING", "Processing"
    REVIEW = "REVIEW", "Review"


class QuarantineReasonChoices(models.TextChoices):
    UNKNOWN_EMPLOYEE = "UNKNOWN_EMPLOYEE", "Unknown employee"
    PERIOD_LOCKED = "PERIOD_LOCKED", "Period locked"
    NO_SHIFT = "NO_SHIFT", "No shift"
    MALFORMED = "MALFORMED", "Malformed"
    FUTURE_DATED = "FUTURE_DATED", "Future-dated"


class AttendanceAuditActionChoices(models.TextChoices):
    PUNCH_INGESTED = "PUNCH_INGESTED", "Punches ingested"
    ADJUSTED = "ADJUSTED", "Adjusted"
    ADJUSTMENT_REMOVED = "ADJUSTMENT_REMOVED", "Adjustment removed"
    EXCEPTION_RESOLVED = "EXCEPTION_RESOLVED", "Exception resolved"
    EXCEPTION_ACKNOWLEDGED = "EXCEPTION_ACKNOWLEDGED", "Exception acknowledged"
    HOLIDAY_WORK_CONFIRMED = "HOLIDAY_WORK_CONFIRMED", "Holiday working confirmed"
    PERIOD_LOCKED = "PERIOD_LOCKED", "Period locked"
    PERIOD_REOPENED = "PERIOD_REOPENED", "Period reopened"
    RECOMPUTED = "RECOMPUTED", "Recomputed"
    CALENDAR_PUBLISHED = "CALENDAR_PUBLISHED", "Calendar published"
    SHIFT_ASSIGNED = "SHIFT_ASSIGNED", "Shift assigned"
