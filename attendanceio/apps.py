from django.apps import AppConfig


class AttendanceioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendanceio"

    def ready(self):
        from .django_rest.signals.attendances import create_attendance_session
