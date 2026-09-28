from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    ScheduledPlanChangeKindChoices,
    ScheduledPlanChangeStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)


class SubscriptionEvent(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="subscription_events",
    )
    company_subscription = models.ForeignKey(
        "subscriptionio.CompanySubscription",
        on_delete=models.CASCADE,
        related_name="events",
        blank=True,
        null=True,
    )
    event_type = models.CharField(
        max_length=40,
        choices=SubscriptionEventTypeChoices,
        db_index=True,
    )
    previous_status = models.CharField(max_length=50, blank=True, null=True)
    new_status = models.CharField(max_length=50, blank=True, null=True)
    source = models.CharField(
        max_length=20,
        choices=SubscriptionEventSourceChoices,
        default=SubscriptionEventSourceChoices.SYSTEM,
    )
    payload = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    stripe_event_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.event_type} company={self.company_id}"


class ScheduledPlanChange(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="scheduled_plan_changes",
    )
    company_subscription = models.ForeignKey(
        "subscriptionio.CompanySubscription",
        on_delete=models.CASCADE,
        related_name="scheduled_plan_changes",
    )
    current_subscription_price = models.ForeignKey(
        "subscriptionio.SubscriptionPrice",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="scheduled_changes_from",
    )
    target_subscription_price = models.ForeignKey(
        "subscriptionio.SubscriptionPrice",
        on_delete=models.CASCADE,
        related_name="scheduled_changes_to",
    )
    scheduled_for = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=ScheduledPlanChangeStatusChoices,
        default=ScheduledPlanChangeStatusChoices.SCHEDULED,
        db_index=True,
    )
    change_kind = models.CharField(
        max_length=20,
        choices=ScheduledPlanChangeKindChoices,
        default=ScheduledPlanChangeKindChoices.DOWNGRADE,
    )
    requires_usage_reduction = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.change_kind} company={self.company_id} ({self.status})"
