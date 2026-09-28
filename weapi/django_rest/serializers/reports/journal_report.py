from collections import defaultdict

from datetime import datetime

from rest_framework.serializers import ModelSerializer
from rest_framework.fields import SerializerMethodField

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from common.django_rest.helpers.ledger_balances import (
    DerivedRunningBalanceMixin,
)

from agencyio.django_rest.serializers.common import PrivateAgencyTaxSlimSerializer

from creditnoteio.django_rest.serializers.common import PrivateCreditNoteSlimSerializer

from customerio.django_rest.serializers.common import (
    PrivateCustomerSlimSerializer,
)

from journalio.models import JournalEntryConnector, JournalEntry
from journalio.django_rest.serializers.common import PrivateJournalEntrySlimSerializer

from supplierio.django_rest.serializers.common import (
    PrivateSupplierSlimSerializer,
)
from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer


class PrivateWeJournalReportListSerializer(DerivedRunningBalanceMixin, ModelSerializer):
    last_balance = SerializerMethodField(read_only=True)
    running_balance = SerializerMethodField(read_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    warehose = PrivateWarehouseSlimSerializer(read_only=True)
    account = PrivateChartOfAccountSlimSerializer(read_only=True)
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)
    journal = PrivateJournalEntrySlimSerializer(read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "title",
            "debit",
            "credit",
            "total",
            "last_balance",
            "running_balance",
            "kind",
            "request_kind",
            "account",
            "journal",
            "supplier",
            "customer",
            "warehose",
            "tax",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "uid",
            "created_at",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # Format the date for grouping
        representation["date"] = datetime.strptime(
            representation["created_at"], "%Y-%m-%dT%H:%M:%S.%f%z"
        ).date()
        return representation


class GroupedJournalReportSerializer:
    def __init__(self, data):
        self.data = data

    def group_by_date(self):
        grouped_data = defaultdict(list)
        for entry in self.data:
            grouped_data[entry["date"]].append(entry)
        return grouped_data

    def to_representation(self):
        grouped_data = self.group_by_date()
        response = []
        for date, entries in grouped_data.items():
            response.append(
                {
                    "date": date,
                    "entries": entries,
                    "total_debit": sum(float(entry["debit"]) for entry in entries),
                    "total_credit": sum(float(entry["credit"]) for entry in entries),
                }
            )
        return response


# New serializers for Journal Entry with Connectors report
class PrivateJournalEntryConnectorSerializer(ModelSerializer):
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    warehose = PrivateWarehouseSlimSerializer(read_only=True)
    account = PrivateChartOfAccountSlimSerializer(read_only=True)
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "debit",
            "credit",
            "kind",
            "request_kind",
            "is_customer_or_supplier_transaction",
            "account",
            "supplier",
            "customer",
            "warehose",
            "tax",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "uid",
            "created_at",
        ]


class PrivateJournalEntryWithConnectorsSerializer(ModelSerializer):
    journalentryconnector_set = PrivateJournalEntryConnectorSerializer(
        many=True, read_only=True
    )
    credit_note = PrivateCreditNoteSlimSerializer(read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "uid",
            "date",
            "amount",
            "status",
            "kind",
            "is_journal_entry",
            "is_transaction",
            "journalentryconnector_set",
            "credit_note",
            "created_at",
        ]
        read_only_fields = [
            "uid",
            "created_at",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        connectors = representation.get("journalentryconnector_set", [])

        # Filter connectors where is_customer_or_supplier_transaction is False
        filtered_connectors = [
            connector
            for connector in connectors
            if not connector.get("is_customer_or_supplier_transaction", False)
        ]
        representation["journalentryconnector_set"] = filtered_connectors

        # Calculate total debit and credit from filtered connectors
        representation["total_debit"] = sum(
            float(connector.get("debit", 0)) for connector in filtered_connectors
        )
        representation["total_credit"] = sum(
            float(connector.get("credit", 0)) for connector in filtered_connectors
        )
        return representation
