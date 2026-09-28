from django.db import models

from common.choices import CurrencyChoices, DiscountKind
from common.models import BaseModelWithUID

from .choices import (
    PlanMigrationJobStatusChoices,
    PlanMigrationRecordStatusChoices,
    SubscriptionContractStatusChoices,
)


class SubscriptionContract(BaseModelWithUID):
    """Enterprise contract overrides for a specific company."""

    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="subscription_contracts",
    )
    subscription_price = models.ForeignKey(
        "subscriptionio.SubscriptionPrice",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="contracts",
    )
    plan_version = models.ForeignKey(
        "subscriptionio.PlanVersion",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="contracts",
    )
    currency = models.CharField(
        max_length=20,
        choices=CurrencyChoices,
        default=CurrencyChoices.USD,
    )
    custom_price = models.DecimalField(
        max_digits=19, decimal_places=3, blank=True, null=True
    )
    custom_discount = models.DecimalField(
        max_digits=19, decimal_places=3, blank=True, null=True
    )
    discount_kind = models.CharField(
        max_length=20,
        choices=DiscountKind,
        default=DiscountKind.FLAT,
    )
    employee_limit_override = models.PositiveIntegerField(blank=True, null=True)
    user_limit_override = models.PositiveIntegerField(blank=True, null=True)
    is_manual_billing = models.BooleanField(default=False)
    contract_start = models.DateTimeField()
    contract_end = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=SubscriptionContractStatusChoices,
        default=SubscriptionContractStatusChoices.ACTIVE,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Contract {self.company_id} ({self.status})"


class PlanMigrationJob(BaseModelWithUID):
    source_subscription = models.ForeignKey(
        "subscriptionio.Subscription",
        on_delete=models.CASCADE,
        related_name="source_migration_jobs",
    )
    target_subscription = models.ForeignKey(
        "subscriptionio.Subscription",
        on_delete=models.CASCADE,
        related_name="target_migration_jobs",
    )
    source_plan_version = models.ForeignKey(
        "subscriptionio.PlanVersion",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="source_migration_jobs",
    )
    target_plan_version = models.ForeignKey(
        "subscriptionio.PlanVersion",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="target_migration_jobs",
    )
    status = models.CharField(
        max_length=20,
        choices=PlanMigrationJobStatusChoices,
        default=PlanMigrationJobStatusChoices.PENDING,
    )
    grandfather_existing = models.BooleanField(
        default=True,
        help_text="Keep companies pinned to their current plan version when set.",
    )
    dry_run = models.BooleanField(default=True)
    total_companies = models.PositiveIntegerField(default=0)
    migrated_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Migration {self.uid} ({self.status})"


class PlanMigrationRecord(BaseModelWithUID):
    job = models.ForeignKey(
        PlanMigrationJob,
        on_delete=models.CASCADE,
        related_name="records",
    )
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="plan_migration_records",
    )
    company_subscription = models.ForeignKey(
        "subscriptionio.CompanySubscription",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=PlanMigrationRecordStatusChoices,
        default=PlanMigrationRecordStatusChoices.SUCCESS,
    )
    message = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.company_id} {self.status}"
