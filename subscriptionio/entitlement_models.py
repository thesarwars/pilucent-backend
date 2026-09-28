from django.db import models
from django.utils.timezone import now

from common.models import BaseModelWithUID

from .choices import (
    FeatureAccessLevelChoices,
    LimitEnforcementModeChoices,
    LimitMetricChoices,
    PlanVersionStatusChoices,
)


class SubscriptionModule(BaseModelWithUID):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.TextField(blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("display_order", "code")

    def __str__(self):
        return self.code


class SubscriptionFeature(BaseModelWithUID):
    module = models.ForeignKey(
        SubscriptionModule,
        on_delete=models.CASCADE,
        related_name="features",
    )
    code = models.CharField(max_length=80, unique=True, db_index=True)
    legacy_field = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        unique=True,
        help_text="Maps to boolean field on Subscription model, e.g. is_sales",
    )
    permission_codenames = models.JSONField(default=list, blank=True)
    api_scope = models.CharField(max_length=120, blank=True, null=True)
    menu_key = models.CharField(max_length=120, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("module__display_order", "code")

    def __str__(self):
        return self.code


class PlanVersion(BaseModelWithUID):
    subscription = models.ForeignKey(
        "subscriptionio.Subscription",
        on_delete=models.CASCADE,
        related_name="plan_versions",
    )
    version_no = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=PlanVersionStatusChoices,
        default=PlanVersionStatusChoices.DRAFT,
    )
    published_at = models.DateTimeField(blank=True, null=True)
    effective_from = models.DateTimeField(blank=True, null=True)
    effective_to = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("-version_no",)
        unique_together = ("subscription", "version_no")

    def __str__(self):
        return f"{self.subscription_id} v{self.version_no} ({self.status})"

    def publish(self):
        self.status = PlanVersionStatusChoices.PUBLISHED
        self.published_at = now()
        if not self.effective_from:
            self.effective_from = now()
        self.save(update_fields=["status", "published_at", "effective_from", "updated_at"])


class PlanLimit(BaseModelWithUID):
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.CASCADE,
        related_name="limits",
    )
    metric_code = models.CharField(max_length=50, choices=LimitMetricChoices)
    included_quantity = models.PositiveIntegerField(default=0)
    min_quantity = models.PositiveIntegerField(default=0)
    max_quantity = models.PositiveIntegerField(blank=True, null=True)
    overage_unit_price = models.DecimalField(
        max_digits=19,
        decimal_places=3,
        default=0,
    )
    enforcement_mode = models.CharField(
        max_length=30,
        choices=LimitEnforcementModeChoices,
        default=LimitEnforcementModeChoices.SOFT_WARNING,
    )
    stripe_overage_price_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional Stripe price ID for recurring overage seats.",
    )

    class Meta:
        unique_together = ("plan_version", "metric_code")

    def __str__(self):
        return f"{self.plan_version_id} {self.metric_code}"


class PlanFeature(BaseModelWithUID):
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    feature = models.ForeignKey(
        SubscriptionFeature,
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    is_enabled = models.BooleanField(default=False)
    access_level = models.CharField(
        max_length=20,
        choices=FeatureAccessLevelChoices,
        default=FeatureAccessLevelChoices.FULL,
    )
    limit_value = models.PositiveIntegerField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("plan_version", "feature")

    def __str__(self):
        return f"{self.plan_version_id} {self.feature.code}"
