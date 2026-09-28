from rest_framework.serializers import ModelSerializer

from paymentio.models import PaymentMethod


class PaymentMethodBaseSerializer(ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["title", "status", "created_at", "updated_at"]
        read_only_fields = fields


class PrivatePaymentMethodSlimSerializer(PaymentMethodBaseSerializer):
    class Meta:
        model = PaymentMethodBaseSerializer.Meta.model
        fields = ["uid"] + PaymentMethodBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicPaymentMethodSlimSerializer(PaymentMethodBaseSerializer):
    class Meta:
        model = PaymentMethodBaseSerializer.Meta.model
        fields = ["slug"] + PaymentMethodBaseSerializer.Meta.fields
        read_only_fields = fields
