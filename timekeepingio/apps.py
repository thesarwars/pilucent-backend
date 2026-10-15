from django.apps import AppConfig


class TimekeepingioConfig(AppConfig):
    """BD attendance (docs/backend/attendance.md). Separate from `attendanceio`,
    the original product's time tracking, which stores hours as floats and
    edits day records in place -- the opposite of punches-as-facts."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "timekeepingio"
    verbose_name = "Attendance (BD)"
