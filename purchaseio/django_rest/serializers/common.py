from rest_framework.serializers import ModelSerializer

from ...models import Purchase, Expense, PurchasePayment, PayBill


class PurchaseBaseSerializer(ModelSerializer):
    class Meta:
        model = Purchase
        fields = [
            "purchase_id",
            "status",
            "tax_kind",
            "due_date",
            "is_bill",
            "total",
            "total_tax",
            "deposit",
            "due_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivatePurchaseSlimSerializer(PurchaseBaseSerializer):
    class Meta:
        model = PurchaseBaseSerializer.Meta.model
        fields = ["uid"] + PurchaseBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicPurchaseSlimSerializer(PurchaseBaseSerializer):
    class Meta:
        model = PurchaseBaseSerializer.Meta.model
        fields = ["slug"] + PurchaseBaseSerializer.Meta.fields
        read_only_fields = fields


class PurchaseBaseSerializer(ModelSerializer):
    class Meta:
        model = Expense
        fields = [
            "expense_id",
            "status",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "total",
            "deposit",
            "due_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateExpenseSlimSerializer(PurchaseBaseSerializer):
    class Meta:
        model = PurchaseBaseSerializer.Meta.model
        fields = ["uid"] + PurchaseBaseSerializer.Meta.fields
        read_only_fields = fields


class PurchasePaymentBaseSerializer(ModelSerializer):
    class Meta:
        model = PurchasePayment
        fields = [
            "bill_number",
            "status",
            "total",
            "deposit",
            "due_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivatePurchasePaymentSlimSerializer(PurchasePaymentBaseSerializer):
    class Meta:
        model = PurchasePaymentBaseSerializer.Meta.model
        fields = ["uid"] + PurchasePaymentBaseSerializer.Meta.fields
        read_only_fields = fields


class PayBillBaseSerializer(ModelSerializer):
    class Meta:
        model = PayBill
        fields = [
            "tracking_number",
            "status",
            "tax_kind",
            "total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivatePayBillSlimSerializer(PayBillBaseSerializer):
    class Meta:
        model = PayBillBaseSerializer.Meta.model
        fields = ["uid"] + PayBillBaseSerializer.Meta.fields
        read_only_fields = fields
