from django.apps import AppConfig


class EmployeeioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "employeeio"

    def ready(self):
        from . import signals  # noqa: F401
