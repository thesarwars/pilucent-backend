from django.apps import AppConfig


class EmployeeioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "employeeio"

    def ready(self):
        from employeeio.django_rest.signals.employees import (  # noqa: F401
            create_private_employee_salary,
            sync_employee_status_to_user,
        )
