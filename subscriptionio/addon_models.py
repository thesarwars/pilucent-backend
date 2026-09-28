from django.db import models

from common.choices import CurrencyChoices
from common.models import BaseModelWithUID

from .choices import (
    AddOnPricingModelChoices,
    AddOnStatusChoices,
    CompanyAddOnStatusChoices,
    LimitMetricChoices,
    PlanAddOnAvailabilityChoices,
    SubscriptionPriceBillingFrequencyChoices,
)


class SubscriptionAddOn(BaseModelWithUID):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    pricing_model = models.CharField(
        max_length=20,
        choices=AddOnPricingModelChoices,
        default=AddOnPricingModelChoices.RECURRING,
    )
    price = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    billing_frequency = models.CharField(
        max_length=50,
        choices=SubscriptionPriceBillingFrequencyChoices,
        blank=True,
        null=True,
    )
    currency = models.CharField(
        max_length=20,
        choices=CurrencyChoices,
        default=CurrencyChoices.USD,
    )
    status = models.CharField(
        max_length=20,
        choices=AddOnStatusChoices,
        default=AddOnStatusChoices.DRAFT,
        db_index=True,
    )
    metric_code = models.CharField(
        max_length=50,
        choices=LimitMetricChoices,
        blank=True,
        null=True,
    )
    unit_label = models.CharField(max_length=100, blank=True)
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)
    applies_to_subscriptions = models.ManyToManyField(
        "subscriptionio.Subscription",
        blank=True,
        related_name="addons",
    )

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.code


class PlanAddOn(BaseModelWithUID):
    plan_version = models.ForeignKey(
        "subscriptionio.PlanVersion",
        on_delete=models.CASCADE,
        related_name="plan_addons",
    )
    add_on = models.ForeignKey(
        SubscriptionAddOn,
        on_delete=models.CASCADE,
        related_name="plan_links",
    )
    availability = models.CharField(
        max_length=20,
        choices=PlanAddOnAvailabilityChoices,
        default=PlanAddOnAvailabilityChoices.OPTIONAL,
    )

    class Meta:
        unique_together = ("plan_version", "add_on")

    def __str__(self):
        return f"{self.plan_version_id}:{self.add_on.code}"


class CompanyAddOn(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="subscription_addons",
    )
    company_subscription = models.ForeignKey(
        "subscriptionio.CompanySubscription",
        on_delete=models.CASCADE,
        related_name="addons",
    )
    add_on = models.ForeignKey(
        SubscriptionAddOn,
        on_delete=models.CASCADE,
        related_name="company_addons",
    )
    status = models.CharField(
        max_length=20,
        choices=CompanyAddOnStatusChoices,
        default=CompanyAddOnStatusChoices.ACTIVE,
        db_index=True,
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    stripe_subscription_item_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.company_id}:{self.add_on.code}"
