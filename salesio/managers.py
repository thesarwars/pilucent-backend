from django.db import models

from .choices import (
    SalesStatusChoices,
    SalePaymentReceiveStatusChoices,
    SalePaymentReceiveItemModelStatusChoices,
)


class SalesQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=SalesStatusChoices.REMOVED)

    def get_status_accepted(self):
        return self.filter(status=SalesStatusChoices.ACCEPTED)

    def get_status_pending(self):
        return self.filter(status=SalesStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=SalesStatusChoices.DRAFT)

    def get_status_open(self):
        return self.filter(status=SalesStatusChoices.OPEN)

    def get_status_closed(self):
        return self.filter(status=SalesStatusChoices.CLOSED)

    def get_status_rejected(self):
        return self.filter(status=SalesStatusChoices.REJECTED)

    def get_customer_due_total(self, customer_uid):
        return self.filter(customer__uid=customer_uid).aggregate(
            sub_total=models.Sum("due_total")
        )["sub_total"]


class SalePaymentReceiveQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=SalePaymentReceiveStatusChoices.REMOVED)

    def get_status_pending(self):
        return self.filter(status=SalePaymentReceiveStatusChoices.PENDING)

    def get_status_partially(self):
        return self.filter(status=SalePaymentReceiveStatusChoices.PARTIALLY)

    def get_status_completed(self):
        return self.filter(status=SalePaymentReceiveStatusChoices.COMPLETED)


class SalePaymentReceiveItemQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(
            status=SalePaymentReceiveItemModelStatusChoices.REMOVED
        )

    def get_status_partially(self):
        return self.filter(status=SalePaymentReceiveItemModelStatusChoices.PARTIALLY)

    def get_status_completed(self):
        return self.filter(status=SalePaymentReceiveItemModelStatusChoices.COMPLETED)
