from django.db.models import QuerySet

from .choices import EmployeeSalaryStatusChoices


class EmployeeSalaryQuerySet(QuerySet):
    # Status filters
    def get_status_all(self):
        return self.all().exclude(status=EmployeeSalaryStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=EmployeeSalaryStatusChoices.ACTIVE)

    def get_status_in_active(self):
        return self.filter(status=EmployeeSalaryStatusChoices.IN_ACTIVE)

    def get_status_removed(self):
        return self.filter(status=EmployeeSalaryStatusChoices.REMOVED)

   