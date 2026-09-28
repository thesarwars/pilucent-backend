import logging
from datetime import datetime
from decimal import Decimal

from rest_framework.generics import get_object_or_404
from rest_framework.serializers import (
    CharField,
    ModelSerializer,
    SlugRelatedField,
    ListField,
    FileField,
    ValidationError,
    JSONField,
    ChoiceField,
    DateField,
    DecimalField,
)

from django.db import transaction

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

from accounts.choices import ChartOfAccountStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.decorators import set_auditlog_actor

from customerio.models import Customer

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.services.files import FileService

from journalio.models import JournalEntry, JournalEntryConnector
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService

from paymentio.models import PaymentMethod

from supplierio.models import Supplier

from tagio.choices import TagStatusChoices, TagKindChoices
from tagio.models import Tag, TagConnector

from transactionio.models import BankDeposit, BankDepositItem

logger = logging.getLogger(__name__)


class PrivateWeBankDepositListCreateSerializer(
    CompanyScopedRelatedFieldsMixin, ModelSerializer
):
    """Serializer for creating and listing bank deposits.

    The mixin closes a cross-tenant ledger write. `bank_chart_of_account_uid`
    and `cash_back_account_uid` resolved against every ACTIVE selectable account
    in the database -- and `create()` calls `update_opening_balance()` on
    whatever they return, then posts connector rows against that account while
    `journal.company` is the caller's. Every *other* account on this serializer
    was already scoped by hand; the omission was on exactly the two legs that
    move money.

    This is the same defect the reconciliation serializer's own docstring
    records as fixed. That fix landed next door and not here.
    """

    bank_chart_of_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    # The account the deposit lands in has to be one money moves through.
    # `cash_back_account_uid` below is deliberately NOT narrowed: cash back
    # comes out of the deposit into an ordinary expense or income account.
    bank_chart_of_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .filter(status=ChartOfAccountStatusChoices.ACTIVE)
        .money(),
        write_only=True,
        required=True,
    )

    cash_back_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    cash_back_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    # Deposit items related
    deposit_items = JSONField(required=False, write_only=True)

    # Read-only fields for response
    total_deposit_amount = DecimalField(max_digits=19, decimal_places=3, read_only=True)
    net_deposit_amount = DecimalField(max_digits=19, decimal_places=3, read_only=True)

    # Tag realted
    tag_title_list = JSONField(required=False, write_only=True)
    # File related
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)

    class Meta:
        model = BankDeposit
        fields = [
            "uid",
            "date",
            "description",
            "bank_chart_of_account",
            "bank_chart_of_account_uid",
            "cash_back_memo",
            "cash_back_amount",
            "cash_back_account",
            "cash_back_account_uid",
            "status",
            "created_by",
            "deposit_items",
            "total_deposit_amount",
            "net_deposit_amount",
            "tag_title_list",
            # File related fields
            "files",
            "file_description",
            "file_uids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "created_by",
            "created_at",
            "updated_at",
            # BR-23. A deposit was created in whatever status the client asked
            # for -- COMPLETED, CANCELLED, anything in the enum -- and since no
            # update or delete path exists for a deposit, that first value is
            # the one it keeps forever. The field is server-owned; it defaults
            # to DRAFT on the model and only a path that does not exist yet
            # should move it.
            "status",
        ]

    def validate(self, validated_data):
        """Cross-field validation"""
        # Check if deposit_items is provided
        if "deposit_items" not in validated_data or not validated_data["deposit_items"]:
            raise ValidationError({"message": "Select at least one deposit item."})

        # Cash back has to go somewhere. The bank leg is posted net of it, so
        # accepting an amount with no account produces a journal entry short by
        # exactly the cash back -- and nothing downstream can tell that it was
        # a missing account rather than arithmetic.
        cash_back_amount = validated_data.get("cash_back_amount") or Decimal("0.00")
        if cash_back_amount > 0 and not validated_data.get("cash_back_account_uid"):
            raise ValidationError(
                {"cash_back_account_uid": "Choose an account for the cash back."}
            )

        return validated_data

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        """Create bank deposit with deposit items and journal entries"""
        # Request user related
        user = self.context["request"].user
        company = user.get_active_company()

        # Extract data
        deposit_items_data = validated_data.pop("deposit_items", [])
        validated_data["bank_chart_of_account"] = validated_data.pop(
            "bank_chart_of_account_uid", None
        )
        bank_chart_of_account = validated_data.get("bank_chart_of_account")
        validated_data["cash_back_account"] = validated_data.pop(
            "cash_back_account_uid", None
        )
        cash_back_account = validated_data.get("cash_back_account")

        tag_title_list = validated_data.pop("tag_title_list", [])
        files = validated_data.pop("files", [])
        file_description = validated_data.pop("file_description", "")
        file_uids = validated_data.pop("file_uids", [])

        # Set basic fields
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company

        # Create bank deposit
        bank_deposit = BankDeposit.objects.create(**validated_data)

        # Initialize connector data for journal entries
        connector_data = []
        total_deposit_amount = Decimal("0.00")
        cash_back_amount = bank_deposit.cash_back_amount or Decimal("0.00")

        # Process each deposit item for journal entries
        for item_data in deposit_items_data:
            item_amount = Decimal(str(item_data["amount"]))
            total_deposit_amount += item_amount

            # Handle journal entry connector for undeposited funds (if provided in item)
            journal_entry_connector_uid = item_data.get("journal_entry_connector_uid")
            if journal_entry_connector_uid:
                journal_entry_connector = get_object_or_404(
                    JournalEntryConnector,
                    uid=journal_entry_connector_uid,
                    journal__company=company,
                )

                # Get the related journal entry
                related_journal_entry = journal_entry_connector.journal

                # Check if it's a deposit entry and update is_deposit flag
                if related_journal_entry.is_deposit:
                    related_journal_entry.is_deposit = False
                    related_journal_entry.save_dirty_fields()

            # Get received from account (required)
            received_from_account_uid = item_data.get("received_from_account_uid")
            received_from_account = get_object_or_404(
                ChartOfAccount,
                uid=received_from_account_uid,
                company=company,
                status=ChartOfAccountStatusChoices.ACTIVE,
            )

            # A deposit always CREDITS the account the money came from, and
            # that account is user-chosen. "substraction" only resolves to
            # CREDIT on assets and expenses; money received from an income,
            # liability or equity account was debited instead, putting it on
            # the wrong side and leaving the entry out by twice the line.
            received_from_action = action_for_side(
                received_from_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            update_opening_balance(
                received_from_account,
                balance_operation_for_action(received_from_action),
                item_amount,
                0,
            )

            # Add to connector data for journal entry
            connector_data.append(
                (
                    received_from_account,
                    received_from_action,
                    item_amount,
                    received_from_account.opening_balance,
                    None,
                )
            )

        # Create deposit items using bulk_create with list comprehension
        created_deposit_items = BankDepositItem.objects.bulk_create(
            [
                BankDepositItem(
                    bank_deposit=bank_deposit,
                    date=item_data.get("date", bank_deposit.date),
                    description=item_data.get("description", ""),
                    reference_number=item_data.get("reference_number", ""),
                    type=item_data["type"],
                    amount=Decimal(str(item_data["amount"])),
                    customer=(
                        get_object_or_404(
                            Customer,
                            uid=item_data["customer_uid"],
                            company=company,
                        )
                        if item_data.get("customer_uid")
                        else None
                    ),
                    supplier=(
                        get_object_or_404(
                            Supplier,
                            uid=item_data["supplier_uid"],
                            company=company,
                        )
                        if item_data.get("supplier_uid")
                        else None
                    ),
                    received_from_account=get_object_or_404(
                        ChartOfAccount,
                        uid=item_data["received_from_account_uid"],
                        company=company,
                        status=ChartOfAccountStatusChoices.ACTIVE,
                    ),
                    payment_method=(
                        get_object_or_404(
                            PaymentMethod,
                            uid=item_data["payment_method_uid"],
                            company=company,
                        )
                        if item_data.get("payment_method_uid")
                        else None
                    ),
                )
                for item_data in deposit_items_data
            ]
        )

        net_deposit_amount = total_deposit_amount - cash_back_amount

        # Depositing always DEBITS the account the money lands in. "addition"
        # resolves to DEBIT only on assets and expenses, so a deposit into a
        # liability-typed account -- a credit card, say -- credited it.
        bank_action = action_for_side(
            bank_chart_of_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            bank_chart_of_account,
            balance_operation_for_action(bank_action),
            net_deposit_amount,
            0,
        )

        # Add bank account to connector data
        connector_data.append(
            (
                bank_chart_of_account,
                bank_action,
                net_deposit_amount,
                bank_chart_of_account.opening_balance,
                None,
            )
        )

        # Handle cash back if applicable.
        # The bank leg above is reduced by the cash-back amount, so this leg has
        # to be a DEBIT for the entry to balance -- money that did not reach the
        # bank went here instead. "addition" only resolves to DEBIT on asset and
        # expense accounts; taking cash back to a liability or equity account
        # posted it as a CREDIT, putting the amount on the wrong side and
        # leaving the entry out of balance by twice the cash back. Production
        # has daily deposits doing exactly that.
        if cash_back_amount > 0 and cash_back_account:
            cash_back_action = action_for_side(
                cash_back_account.kind, JournalEntryConnectorKindChoices.DEBIT
            )
            update_opening_balance(
                cash_back_account,
                balance_operation_for_action(cash_back_action),
                cash_back_amount,
                0,
            )

            # Add cash back account to connector data
            connector_data.append(
                (
                    cash_back_account,
                    cash_back_action,
                    cash_back_amount,
                    cash_back_account.opening_balance,
                    None,
                )
            )
        elif cash_back_amount > 0:
            # The bank leg was already netted down by this amount, so with no
            # account to take it to the entry is short by exactly the cash back
            # and nothing said so. `validate` now refuses this combination;
            # the log covers rows created before that guard existed.
            logger.error(
                "bank deposit for company %s takes %s of cash back but names no "
                "account for it. The bank leg is reduced by that amount, so the "
                "journal entry will not balance.",
                getattr(company, "pk", None), cash_back_amount,
            )

        # Create journal entry
        if connector_data:
            journal_entry = JournalEntryService.create_journal_entry(
                amount=total_deposit_amount,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.BANK_DEPOSIT,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=bank_deposit,
            )

            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=total_deposit_amount,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                created_by=user.get_employee(),
            )

        # Handle tags
        if tag_title_list:
            tag_connectors = []
            for tag_title in tag_title_list:
                tag, created = Tag.objects.get_or_create(
                    title=tag_title,
                    company=company,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.BANK_DEPOSIT,
                    },
                )
                tag_connectors.append(
                    TagConnector(
                        tag=tag,
                        bank_deposit=bank_deposit,
                    )
                )

            TagConnector.objects.bulk_create(tag_connectors)

        # Handle files
        if files or file_uids:
            # NB: the method is create_file_item_connector -- create_files does
            # not exist, so attaching a file to a deposit used to AttributeError.
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=company,
                model_kind=FileItemConnectorModelKindChoices.BANK_DEPOSIT,
                object=bank_deposit,
            )

        return bank_deposit
