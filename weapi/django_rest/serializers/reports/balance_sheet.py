from rest_framework import serializers
from journalio.models import JournalEntryConnector
import django_filters
from collections import defaultdict
from accounts.models import ChartOfAccount


class BalanceSheetDetailsSerializer(serializers.ModelSerializer):
    """
    Serializer for balance sheet details.
    """

    co_account = serializers.CharField(source="account.title")
    co_account_head = serializers.CharField(source="account.kind")
    customer = serializers.CharField(source="customer.first_name", read_only=True)
    supplier = serializers.CharField(source="supplier.first_name", read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "slug",
            "debit",
            "credit",
            "total",
            "last_balance",
            "kind",
            "request_kind",
            "co_account",
            "co_account_head",
            "journal",
            "supplier",
            "customer",
            "warehose",
            "tax",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "slug", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        acc = instance.account
        kind = instance.kind
        acc_kind = instance.account.kind
        # data['opening_balance'] = instance.account.opening_balance

        if (acc_kind == "ASSETS" and kind == "DEBIT") or (
            acc_kind in ["EQUITIES", "LIABILITIES"] and kind == "CREDIT"
        ):
            data["amount"] = float(instance.debit or instance.credit or 0)
            # data["last_balance"] = float(instance.last_balance or 0) + float(instance.debit or instance.credit or 0)
        elif (acc_kind == "ASSETS" and kind == "CREDIT") or (
            acc_kind in ["EQUITIES", "LIABILITIES"] and kind == "DEBIT"
        ):
            data["amount"] = -float(instance.credit or instance.debit or 0)
            # data["last_balance"] = float(instance.last_balance or 0) - float(instance.credit or instance.debit or 0)

        return data


class BalanceSheetFilter(django_filters.FilterSet):
    """
    Filter class for filtering balance sheet entries.
    """

    created_at_after = django_filters.DateFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_at_before = django_filters.DateFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = JournalEntryConnector
        fields = [
            "created_at_after",
            "created_at_after",
            "kind",
            "account",
        ]


class PrivateWeBalanceSheetSummarySerializer(serializers.ModelSerializer):

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "opening_balance",
            "kind",
            "created_at",
            "updated_at",
        ]


class PrivateWeBalanceSheetListSerializer(serializers.ModelSerializer):

    class Meta:
        model = ChartOfAccount
        fields = ["uid", "title", "opening_balance", "kind", "created_at", "updated_at"]
