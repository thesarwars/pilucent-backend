from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    NotificationModelKindChoices,
    NotificationKindChoices,
    NotificationStatusChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_notification_slug,
    get_notification_setting_slug,
)


# Create your models here.
class Notification(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_notification_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=NotificationStatusChoices,
        default=NotificationStatusChoices.DRAFT,
        db_index=True,
    )
    model_kind = models.CharField(max_length=50, choices=NotificationModelKindChoices)
    kind = models.CharField(max_length=50, choices=NotificationKindChoices)
    message = models.CharField(max_length=100, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    is_company = models.BooleanField(default=False)

    # FK
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_payment = models.ForeignKey(
        "purchaseio.PurchasePayment", on_delete=models.CASCADE, blank=True, null=True
    )
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.CASCADE, blank=True, null=True
    )
    sale_payment_receive = models.ForeignKey(
        "salesio.SalePaymentReceive", on_delete=models.CASCADE, blank=True, null=True
    )
    inbox = models.ForeignKey(
        "messageio.Inbox", on_delete=models.CASCADE, blank=True, null=True
    )
    stock_alert = models.ForeignKey(
        "stockio.StockAlert", on_delete=models.CASCADE, blank=True, null=True
    )

    def mark_as_read(self):
        self.is_read = True
        self.save_dirty_fields()

    def mark_as_company_notification(self):
        self.is_company = True
        self.save_dirty_fields()

    def __str__(self):
        return f"ID: {self.id}, Kind: {self.kind}"


class NotificationSetting(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_notification_setting_slug, unique=True, db_index=True
    )

    # FK
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, blank=True, null=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}"
