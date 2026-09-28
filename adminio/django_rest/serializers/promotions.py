from rest_framework import serializers

from subscriptionio.models import SubscriptionCoupon, SubscriptionOffer
from subscriptionio.services.admin_coupon_service import AdminCouponService


class AdminSubscriptionCouponPlanSerializer(serializers.Serializer):
    uid = serializers.UUIDField()
    title = serializers.CharField()
    slug = serializers.CharField()


class AdminSubscriptionCouponSerializer(serializers.ModelSerializer):
    applies_to_subscriptions = AdminSubscriptionCouponPlanSerializer(
        many=True, read_only=True
    )
    applies_to_subscription_uids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = SubscriptionCoupon
        fields = [
            "uid",
            "code",
            "status",
            "discount_kind",
            "discount_value",
            "max_redemptions",
            "redemption_count",
            "max_redemptions_per_company",
            "valid_from",
            "valid_until",
            "is_stackable",
            "stripe_coupon_id",
            "notes",
            "applies_to_subscriptions",
            "applies_to_subscription_uids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "redemption_count", "stripe_coupon_id", "created_at", "updated_at"]

    def validate_code(self, value):
        return (value or "").strip().upper()

    def create(self, validated_data):
        uids = validated_data.pop("applies_to_subscription_uids", None)
        coupon = super().create(validated_data)
        if uids is not None:
            AdminCouponService.set_applies_to_subscriptions(coupon, uids)
        return coupon

    def update(self, instance, validated_data):
        uids = validated_data.pop("applies_to_subscription_uids", None)
        coupon = super().update(instance, validated_data)
        if uids is not None:
            AdminCouponService.set_applies_to_subscriptions(coupon, uids)
        return coupon

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["applies_to_subscriptions"] = [
            {
                "uid": str(sub.uid),
                "title": sub.title,
                "slug": sub.slug,
            }
            for sub in instance.applies_to_subscriptions.all()
        ]
        return data


class AdminSubscriptionOfferSerializer(serializers.ModelSerializer):
    coupon = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=SubscriptionCoupon.objects.all(),
        required=False,
        allow_null=True,
    )
    coupon_code = serializers.CharField(source="coupon.code", read_only=True)

    class Meta:
        model = SubscriptionOffer
        fields = [
            "uid",
            "code",
            "title",
            "description",
            "status",
            "coupon",
            "coupon_code",
            "is_retention_offer",
            "valid_from",
            "valid_until",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate_code(self, value):
        return (value or "").strip().upper()
