from rest_framework.serializers import ModelSerializer, CharField, DecimalField, SlugRelatedField

from journalio.models import JournalEntry, JournalEntryConnector
from agencyio.django_rest.serializers.common import PrivateAgencyTaxSlimSerializer
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from accounts.models import ChartOfAccount
from supplierio.models import Supplier
from customerio.models import Customer

from supplierio.django_rest.serializers.common import PrivateSupplierSlimSerializer

from customerio.django_rest.serializers.common import PrivateCustomerSlimSerializer

from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

class JournalEntryBaseSerializer(ModelSerializer):
    class Meta:
        model = JournalEntry
        fields = [
            "date",
            "entry_number",
            "amount",
            "status",
            "kind",
            "is_journal_entry",
            "is_transaction",
            "created_at",
            "updated_at"
        ]
        read_only_fields = fields


class PrivateJournalEntrySlimSerializer(JournalEntryBaseSerializer):
    class Meta:
        model = JournalEntryBaseSerializer.Meta.model
        fields = ["uid"] + JournalEntryBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicJournalEntrySlimSerializer(JournalEntryBaseSerializer):
    class Meta:
        model = JournalEntryBaseSerializer.Meta.model
        fields = ["slug"] + JournalEntryBaseSerializer.Meta.fields
        read_only_fields = fields


class JournalEntryConnectorBaseSerializer(ModelSerializer):
    class Meta:
        model = JournalEntryConnector
        fields = ["debit", "credit", "kind"]


class PrivateJournalEntryConnectorSlimSerializer(CompanyScopedRelatedFieldsMixin, JournalEntryConnectorBaseSerializer):
    account = SlugRelatedField(slug_field='uid', queryset=ChartOfAccount.objects.selectable().all())
    supplier = SlugRelatedField(slug_field='uid', queryset=Supplier.objects.selectable(), required=False)
    customer = SlugRelatedField(slug_field='uid', queryset=Customer.objects.selectable().all(), required=False)
    class Meta:
        model = JournalEntryConnectorBaseSerializer.Meta.model
        fields = ["uid", "account", "supplier", "customer", "description"] + JournalEntryConnectorBaseSerializer.Meta.fields
        # read_only_fields = fields


class PublicJournalEntryConnectorSlimSerializer(JournalEntryConnectorBaseSerializer):
    class Meta:
        model = JournalEntryConnectorBaseSerializer.Meta.model
        fields = ["slug"] + JournalEntryConnectorBaseSerializer.Meta.fields
        read_only_fields = fields


class JournalEntryConnectorListSerializer(ModelSerializer):
    account = PrivateChartOfAccountSlimSerializer(read_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    # warehose = PrivateWarehouseSlimSerializer(read_only=True)
    # tax = PrivateAgencyTaxSlimSerializer(read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "date",
            "debit",
            "credit",
            "kind",
            "supplier",
            "customer",
            # "warehose",
            "account",
            # "tax",
        ]

class PrivateJournalEntryLastBalanceConnectorSlimSerializer(ModelSerializer):
    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "last_balance",
        ]
