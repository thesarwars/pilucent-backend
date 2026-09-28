from django.db import models

from .choices import (
    StockAlertStatusChoices,
    StockAdjustmentStatusChoices,
    StockAdjustmentItemStatusChoices,
)


class StockAlertQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=StockAlertStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=StockAlertStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=StockAlertStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=StockAlertStatusChoices.DRAFT)


class StockAdjustmentQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=StockAdjustmentStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=StockAdjustmentStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=StockAdjustmentStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=StockAdjustmentStatusChoices.DRAFT)


class StockAdjustmentItemQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=StockAdjustmentItemStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=StockAdjustmentItemStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=StockAdjustmentItemStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=StockAdjustmentItemStatusChoices.DRAFT)
