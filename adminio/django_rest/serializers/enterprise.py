from rest_framework import serializers

from subscriptionio.models import (
    PlanMigrationJob,
    PlanMigrationRecord,
    SubscriptionContract,
    SubscriptionPrice,
)


class AdminSubscriptionPriceCurrencySerializer(serializers.ModelSerializer):
    plan_title = serializers.CharField(source="subscription.title", read_only=True)

    class Meta:
        model = SubscriptionPrice
        fields = [
            "uid",
            "subscription",
            "plan_title",
            "billing_frequency",
            "currency",
            "price",
            "discount",
            "discount_kind",
            "stripe_price_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]


class AdminSubscriptionContractSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = SubscriptionContract
        fields = [
            "uid",
            "company",
            "company_name",
            "subscription_price",
            "plan_version",
            "currency",
            "custom_price",
            "custom_discount",
            "discount_kind",
            "employee_limit_override",
            "user_limit_override",
            "is_manual_billing",
            "contract_start",
            "contract_end",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]


class AdminPlanMigrationJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMigrationJob
        fields = [
            "uid",
            "source_subscription",
            "target_subscription",
            "source_plan_version",
            "target_plan_version",
            "status",
            "grandfather_existing",
            "dry_run",
            "total_companies",
            "migrated_count",
            "failed_count",
            "skipped_count",
            "error_log",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "status",
            "total_companies",
            "migrated_count",
            "failed_count",
            "skipped_count",
            "error_log",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]


class AdminPlanMigrationRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMigrationRecord
        fields = [
            "uid",
            "company",
            "company_subscription",
            "status",
            "message",
            "created_at",
        ]
        read_only_fields = fields


class AdminManualInvoiceCreateSerializer(serializers.Serializer):
    company_uid = serializers.UUIDField()
    currency = serializers.CharField(max_length=20)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    mark_paid = serializers.BooleanField(required=False, default=False)
    lines = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )
