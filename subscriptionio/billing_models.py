from django.db import models

from common.choices import CurrencyChoices
from common.models import BaseModelWithUID

from .choices import (
    SubscriptionInvoiceLineTypeChoices,
    SubscriptionInvoiceStatusChoices,
)


class SubscriptionInvoice(BaseModelWithUID):
    status = models.CharField(
        max_length=20,
        choices=SubscriptionInvoiceStatusChoices,
        default=SubscriptionInvoiceStatusChoices.DRAFT,
        db_index=True,
    )
    currency = models.CharField(
        max_length=20,
        choices=CurrencyChoices,
        default=CurrencyChoices.USD,
    )
    subtotal = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    discount_total = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    tax_total = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    total = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    period_start = models.DateTimeField(blank=True, null=True)
    period_end = models.DateTimeField(blank=True, null=True)
    stripe_invoice_id = models.CharField(
        max_length=255, blank=True, null=True, unique=True, db_index=True
    )
    hosted_invoice_url = models.URLField(blank=True, null=True)
    billing_reason = models.CharField(max_length=50, blank=True, null=True)
    is_manual = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="subscription_invoices",
    )
    company_subscription = models.ForeignKey(
        "subscriptionio.CompanySubscription",
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    subscription_price = models.ForeignKey(
        "subscriptionio.SubscriptionPrice",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    payment_information = models.ForeignKey(
        "paymentio.PaymentInformation",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="subscription_invoices",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Invoice {self.uid} ({self.status})"


class SubscriptionInvoiceLine(BaseModelWithUID):
    line_type = models.CharField(
        max_length=20,
        choices=SubscriptionInvoiceLineTypeChoices,
        default=SubscriptionInvoiceLineTypeChoices.BASE,
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=19, decimal_places=3, default=1)
    unit_amount = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    amount = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    metadata = models.JSONField(default=dict, blank=True)

    invoice = models.ForeignKey(
        SubscriptionInvoice,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"{self.line_type}: {self.description}"
