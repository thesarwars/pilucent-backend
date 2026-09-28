from rest_framework.serializers import (
    ModelSerializer,
    DecimalField,
    IntegerField,
    SerializerMethodField,
)

from accounts.models import ChartOfAccount


class PrivateWeDashboardFinanceOverviewSerializer(ModelSerializer):
    supplier_count = IntegerField(source="get_supplier_count")
    customer_count = IntegerField(source="get_customer_count")
    invoice_count = IntegerField(source="get_invoice_count")
    bill_count = IntegerField(source="get_bill_count")

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "opening_balance",
            "supplier_count",
            "customer_count",
            "invoice_count",
            "bill_count",
        ]
        read_only_fields = fields


class PrivateWeDashboardBankOverviewSerializer(ModelSerializer):
    # SerializerMethodField()

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "opening_balance",
            "bank_balance"
        ]
        read_only_fields = fields
