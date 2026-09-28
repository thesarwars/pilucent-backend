from rest_framework import serializers

from subscriptionio.models import SubscriptionInvoice, SubscriptionInvoiceLine


class SubscriptionInvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionInvoiceLine
        fields = [
            "uid",
            "line_type",
            "description",
            "quantity",
            "unit_amount",
            "amount",
            "metadata",
        ]


class SubscriptionInvoiceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionInvoice
        fields = [
            "uid",
            "status",
            "currency",
            "subtotal",
            "discount_total",
            "tax_total",
            "total",
            "period_start",
            "period_end",
            "hosted_invoice_url",
            "billing_reason",
            "created_at",
        ]


class SubscriptionInvoiceDetailSerializer(SubscriptionInvoiceListSerializer):
    lines = SubscriptionInvoiceLineSerializer(many=True, read_only=True)

    class Meta(SubscriptionInvoiceListSerializer.Meta):
        fields = SubscriptionInvoiceListSerializer.Meta.fields + [
            "stripe_invoice_id",
            "lines",
        ]
