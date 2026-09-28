from rest_framework.serializers import ModelSerializer, CharField
from rest_framework.fields import SerializerMethodField

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from common.django_rest.helpers.ledger_balances import (
    DerivedRunningBalanceMixin,
)

from creditnoteio.django_rest.serializers.common import PrivateCreditNoteSlimSerializer

from customerio.django_rest.serializers.common import PrivateCustomerSlimSerializer

from journalio.models import JournalEntry, JournalEntryConnector

from purchaseio.django_rest.serializers.common import (
    PrivatePurchaseSlimSerializer,
    PrivateExpenseSlimSerializer,
    PrivatePurchasePaymentSlimSerializer,
    PrivatePayBillSlimSerializer,
)

from salesio.django_rest.serializers.common import (
    PrivateSaleSerializer,
    PrivateSalePaymentReceiveSlimSerializer,
)

from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer

from supplierio.django_rest.serializers.common import PrivateSupplierSlimSerializer


class PrivateWeJournalEntryListSerializer(ModelSerializer):
    purchase = PrivatePurchaseSlimSerializer(read_only=True)
    expense = PrivateExpenseSlimSerializer(read_only=True)
    purchase_payment = PrivatePurchasePaymentSlimSerializer(read_only=True)
    pay_bill = PrivatePayBillSlimSerializer(read_only=True)
    sale = PrivateSaleSerializer(read_only=True)
    sale_payment_receive = PrivateSalePaymentReceiveSlimSerializer(read_only=True)
    credit_note = PrivateCreditNoteSlimSerializer(read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "uid",
            "entry_number",
            "kind",
            "purchase",
            "expense",
            "purchase_payment",
            "pay_bill",
            "sale",
            "sale_payment_receive",
            "credit_note",
            "created_at",
            "updated_at",
        ]


class PrivateWeGeneralLadgerListSerializer(DerivedRunningBalanceMixin, ModelSerializer):
    last_balance = SerializerMethodField(read_only=True)
    running_balance = SerializerMethodField(read_only=True)
    model_kind = CharField(source="get_model_kind", read_only=True)
    journal = PrivateWeJournalEntryListSerializer(read_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    warehose = PrivateWarehouseSlimSerializer(read_only=True)
    account = PrivateChartOfAccountSlimSerializer(read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "debit",
            "credit",
            "total",
            "last_balance",
            "running_balance",
            "kind",
            "request_kind",
            "model_kind",
            "journal",
            "supplier",
            "customer",
            "warehose",
            "account",
            "created_at",
            "updated_at",
        ]
