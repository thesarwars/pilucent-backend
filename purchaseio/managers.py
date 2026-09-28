from django.db import models

from .choices import (
    PurchasePaymentStatusChoices,
    PurchasePaymentItemStatusChoices,
)


class PurchasePaymentStatusQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=PurchasePaymentStatusChoices.REMOVED)

    def get_status_pending(self):
        return self.filter(status=PurchasePaymentStatusChoices.PENDING)

    def get_status_partially(self):
        return self.filter(status=PurchasePaymentStatusChoices.PARTIALLY)

    def get_status_completed(self):
        return self.filter(status=PurchasePaymentStatusChoices.COMPLETED)

    def get_status_draft(self):
        return self.filter(status=PurchasePaymentStatusChoices.DRAFT)


class PurchasePaymentItemStatusQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=PurchasePaymentItemStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=PurchasePaymentItemStatusChoices.ACTIVE)

    def get_status_partially(self):
        return self.filter(status=PurchasePaymentItemStatusChoices.PARTIALLY)

    def get_status_completed(self):
        return self.filter(status=PurchasePaymentItemStatusChoices.COMPLETED)

    def get_status_draft(self):
        return self.filter(status=PurchasePaymentItemStatusChoices.DRAFT)
