from django.db import models

from common.models import BaseModelWithUID

from .choices import LimitEnforcementModeChoices, LimitMetricChoices


class SubscriptionBillableMetric(BaseModelWithUID):
    code = models.CharField(
        max_length=50,
        choices=LimitMetricChoices,
        unique=True,
        db_index=True,
    )
    title = models.CharField(max_length=120)
    unit_label = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    default_enforcement_mode = models.CharField(
        max_length=30,
        choices=LimitEnforcementModeChoices,
        default=LimitEnforcementModeChoices.SOFT_WARNING,
    )
    default_overage_unit_price = models.DecimalField(
        max_digits=19,
        decimal_places=3,
        default=0,
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("display_order", "code")

    def __str__(self):
        return self.code
