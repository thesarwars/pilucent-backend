from rest_framework.fields import DecimalField
from rest_framework.fields import SerializerMethodField

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from common.django_rest.helpers.ledger_balances import (
    DerivedRunningBalanceMixin,
)

from journalio.models import JournalEntryConnector


class PrivateWeTrialBalanceListSerializer(PrivateChartOfAccountSlimSerializer):
    total_debit = DecimalField(
        source="get_total_debit", max_digits=19, decimal_places=3, read_only=True
    )
    total_credit = DecimalField(
        source="get_total_credit", max_digits=19, decimal_places=3, read_only=True
    )

    class Meta:
        model = PrivateChartOfAccountSlimSerializer.Meta.model
        fields = PrivateChartOfAccountSlimSerializer.Meta.fields + [
            "total_debit",
            "total_credit",
        ]


class PrivateWeTransactionListSerializer(DerivedRunningBalanceMixin, PrivateChartOfAccountSlimSerializer):
    last_balance = SerializerMethodField(read_only=True)
    running_balance = SerializerMethodField(read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "transaction_id",
            "title",
            "debit",
            "credit",
            "last_balance",
            "running_balance",
            "kind",
            "request_kind",
            "description",
            "created_at",
            "updated_at",
        ]
