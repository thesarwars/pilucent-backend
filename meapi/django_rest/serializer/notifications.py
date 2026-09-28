from rest_framework.serializers import ModelSerializer

from accounts.django_rest.serializers.common import PriateUserSlimSerializer

from purchaseio.django_rest.serializers.common import PrivatePurchaseSlimSerializer

from salesio.django_rest.serializers.common import PrivateSaleSerializer

from notificationio.models import Notification


class PrivateMeNotificationListSerializer(ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "uid",
            "status",
            "model_kind",
            "kind",
            "message",
            "is_read",
            "is_company",
            "created_at",
            "updated_at",
        ]


class PrivateMeNotificationDetailsSerializer(ModelSerializer):
    sale = PrivateSaleSerializer(read_only=True)
    purchase = PrivatePurchaseSlimSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "uid",
            "status",
            "model_kind",
            "kind",
            "message",
            "is_read",
            "is_company",
            "purchase",
            "purchase_payment",
            "sale",
            "sale_payment_receive",
            "inbox",
            "stock_alert",
            "created_at",
            "updated_at",
        ]
