from django.db import models

from common.models import BaseModelWithUID

from .choices import LimitMetricChoices


class UsageCounter(BaseModelWithUID):
    """Latest usage quantity per company and metric (refreshed by snapshot job)."""

    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="usage_counters",
    )
    metric_code = models.CharField(max_length=50, choices=LimitMetricChoices)
    quantity = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=30, default="snapshot")

    class Meta:
        unique_together = ("company", "metric_code")
        ordering = ("metric_code",)

    def __str__(self):
        return f"{self.company_id} {self.metric_code}={self.quantity}"
