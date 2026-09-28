from rest_framework import serializers

from subscriptionio.models import (
    PlanFeature,
    PlanLimit,
    PlanVersion,
    SubscriptionFeature,
    SubscriptionModule,
)


class AdminSubscriptionFeatureSerializer(serializers.ModelSerializer):
    module_code = serializers.CharField(source="module.code", read_only=True)

    class Meta:
        model = SubscriptionFeature
        fields = [
            "uid",
            "code",
            "title",
            "module_code",
            "legacy_field",
            "permission_codenames",
            "api_scope",
            "menu_key",
            "is_active",
        ]


class AdminSubscriptionModuleSerializer(serializers.ModelSerializer):
    features = AdminSubscriptionFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = SubscriptionModule
        fields = [
            "uid",
            "code",
            "title",
            "description",
            "display_order",
            "is_active",
            "features",
        ]


class AdminPlanLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanLimit
        fields = [
            "uid",
            "metric_code",
            "included_quantity",
            "min_quantity",
            "max_quantity",
            "overage_unit_price",
            "stripe_overage_price_id",
            "enforcement_mode",
        ]


class AdminPlanFeatureSerializer(serializers.ModelSerializer):
    feature_code = serializers.CharField(source="feature.code", read_only=True)

    class Meta:
        model = PlanFeature
        fields = [
            "uid",
            "feature_code",
            "is_enabled",
            "access_level",
            "limit_value",
            "metadata",
        ]


class AdminPlanVersionSerializer(serializers.ModelSerializer):
    limits = AdminPlanLimitSerializer(many=True, read_only=True)
    plan_features = AdminPlanFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = PlanVersion
        fields = [
            "uid",
            "version_no",
            "status",
            "published_at",
            "effective_from",
            "effective_to",
            "notes",
            "limits",
            "plan_features",
            "created_at",
        ]
