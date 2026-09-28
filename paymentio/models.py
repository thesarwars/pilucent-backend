from autoslug import AutoSlugField

from django.db import models

from common.choices import CurrencyChoices
from common.models import BaseModelWithUID

from .choices import (
    PaymentMethodStatusChoices,
    PaymentInformationKindChoices,
    PaymentInformationStatusChoices,
)
from .managers import PaymentMethodQuerySet
from .django_rest.helpers.slug_helpers import get_payment_information_slug


class PaymentMethod(BaseModelWithUID):
    status = models.CharField(
        max_length=50,
        choices=PaymentMethodStatusChoices,
        default=PaymentMethodStatusChoices.DRAFT,
    )

    # FK
    company = models.ForeignKey("companyio.Company", models.CASCADE)
    objects = PaymentMethodQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Company: {self.company.name}"


class PaymentInformation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payment_information_slug, unique=True, db_index=True
    )

    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    currency = models.CharField(
        choices=CurrencyChoices,
        max_length=20,
        default=CurrencyChoices.USD,
    )
    status = models.CharField(
        max_length=50,
        choices=PaymentInformationStatusChoices,
        default=PaymentInformationStatusChoices.DRAFT,
        db_index=True,
    )
    kind = models.CharField(
        max_length=50,
        choices=PaymentInformationKindChoices,
        default=PaymentInformationKindChoices.COMPANY_SUBSCRIPTION,
        db_index=True,
    )
    payment_intent_id = models.CharField(max_length=250)
    stripe_invoice_id = models.CharField(max_length=250, blank=True, null=True)
    stripe_invoice_url = models.URLField(blank=True, null=True)
    client_secret = models.CharField(max_length=255, blank=True)
    invoice_link = models.URLField(blank=True, null=True)
    response_payload = models.JSONField(default=dict)
    is_subscription_completed = models.BooleanField(default=False)

    # FK
    # TODO: "subscription and subscription_price will not have blank=true and null=true as these are mendatory"
    subscription = models.ForeignKey(
        "subscriptionio.Subscription", on_delete=models.CASCADE, blank=True, null=True
    )
    subscription_price = models.ForeignKey(
        "subscriptionio.SubscriptionPrice",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    payment_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, blank=True, null=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, blank=True, null=True
    )

    def __str__(self):
        return f"ID:{self.id}, Slug:{self.slug}"
