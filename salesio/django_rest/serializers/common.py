from rest_framework.serializers import ModelSerializer

from ...models import Sale, SalePaymentReceive


class SaleBaseSerializer(ModelSerializer):
    class Meta:
        model = Sale
        fields = [
            "invoice_id",
            "status",
            "tax_kind",
            "due_date",
            "is_invoice",
            "is_estimated",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateSaleSerializer(SaleBaseSerializer):
    class Meta:
        model = SaleBaseSerializer.Meta.model
        fields = ["uid"] + SaleBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicSaleSerializer(SaleBaseSerializer):
    class Meta:
        model = SaleBaseSerializer.Meta.model
        fields = ["slug"] + SaleBaseSerializer.Meta.fields
        read_only_fields = fields


class SalePaymentReceiveBaseSerializer(ModelSerializer):
    class Meta:
        model = SalePaymentReceive
        fields = [
            "reference_number",
            "total",
            "deposit",
            "due_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateSalePaymentReceiveSlimSerializer(SalePaymentReceiveBaseSerializer):
    class Meta:
        model = SalePaymentReceiveBaseSerializer.Meta.model
        fields = ["uid"] + SalePaymentReceiveBaseSerializer.Meta.fields
        read_only_fields = fields
