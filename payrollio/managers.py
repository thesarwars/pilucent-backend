from django.db import models

from .choicess import SalaryAdjustmentStatusChoices, SalaryAdjustmentKindChoices, PayScheduleStatusChoice, PayrollWorkLocationChoices


class SalaryAdjustmentQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=SalaryAdjustmentStatusChoices.REMOVED)

    def get_status_draft(self):
        return self.filter(status=SalaryAdjustmentStatusChoices.DRAFT)

    def get_status_active(self):
        return self.filter(status=SalaryAdjustmentStatusChoices.ACTIVE)

    def get_status_inactive(self):
        return self.filter(status=SalaryAdjustmentStatusChoices.IN_ACTIVE)

    def get_kind_addition(self):
        return self.filter(kind=SalaryAdjustmentKindChoices.ADDITION)

    def get_kind_deduction(self):
        return self.filter(kind=SalaryAdjustmentKindChoices.DEDUCTION)


class SalaryAdjustmentManager(models.Manager):
    def get_queryset(self):
        return SalaryAdjustmentQuerySet(self.model, using=self._db)

    def get_status_all(self):
        return self.get_queryset().get_status_all()

    def get_status_draft(self):
        return self.get_queryset().get_status_draft()

    def get_status_active(self):
        return self.get_queryset().get_status_active()

    def get_status_inactive(self):
        return self.get_queryset().get_status_inactive()

    def get_kind_addition(self):
        return self.get_queryset().get_kind_addition()

    def get_kind_deduction(self):
        return self.get_queryset().get_kind_deduction()


class PayScheduleQueryset(models.QuerySet):
    def get_status_active(self):
        return self.filter(status=PayScheduleStatusChoice.ACTIVE)
    

class PayrollWorkLocationQueryset(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=PayrollWorkLocationChoices.REMOVED)

    def get_status_draft(self):
        return self.filter(status=PayrollWorkLocationChoices.DRAFT)

    def get_status_active(self):
        return self.filter(status=PayrollWorkLocationChoices.ACTIVE)

    def get_status_inactive(self):
        return self.filter(status=PayrollWorkLocationChoices.IN_ACTIVE)