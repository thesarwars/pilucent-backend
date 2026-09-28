from django.db import models

from .choices import (
    CompanyDesignationStatusChoices,
    CompanySectionStatusChoices,
    CompanyDepartmentStatusChoices,
    CompanyShiftStatusChoices,
)


class CompanyDesignationQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=CompanyDesignationStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=CompanyDesignationStatusChoices.ACTIVE)

    def get_status_in_active(self):
        return self.filter(status=CompanyDesignationStatusChoices.IN_ACTIVE)

    def get_status_draft(self):
        return self.filter(status=CompanyDesignationStatusChoices.DRAFT)


class CompanySectionQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=CompanySectionStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=CompanySectionStatusChoices.ACTIVE)

    def get_status_in_active(self):
        return self.filter(status=CompanySectionStatusChoices.IN_ACTIVE)

    def get_status_draft(self):
        return self.filter(status=CompanySectionStatusChoices.DRAFT)


class CompanyDepartmentQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=CompanyDepartmentStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=CompanyDepartmentStatusChoices.ACTIVE)

    def get_status_in_active(self):
        return self.filter(status=CompanyDepartmentStatusChoices.IN_ACTIVE)

    def get_status_draft(self):
        return self.filter(status=CompanyDepartmentStatusChoices.DRAFT)


class CompanyShiftQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=CompanyShiftStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=CompanyShiftStatusChoices.ACTIVE)

    def get_status_in_active(self):
        return self.filter(status=CompanyShiftStatusChoices.IN_ACTIVE)

    def get_status_draft(self):
        return self.filter(status=CompanyShiftStatusChoices.DRAFT)
