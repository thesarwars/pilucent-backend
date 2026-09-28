from rest_framework.generics import get_object_or_404

from rest_framework.serializers import ModelSerializer
from rest_framework.serializers import (
    CharField,
    ChoiceField,
    DecimalField,
    FileField,
    ModelSerializer,
    JSONField,
    ListField,
    ValidationError,
    SlugRelatedField,
)

from django.db import transaction

from accounts.choices import ChartOfAccountStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from accounts.models import ChartOfAccount

from common.choices import CurrencyChoices
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    inverse_balance_operation,
    update_opening_balance,
)
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from weapi.django_rest.helpers.pay_bill_application import (
    apply_pay_bill_item,
    resolve_bill_allocations,
    unapply_pay_bill_item,
)
from common.django_rest.helpers.decorators import set_auditlog_actor

from currencyio.choices import CurrencyConnectorModelKind
from currencyio.django_rest.serializers.common import PrivateCurrencySlimSerializer
from currencyio.models import Currency, CurrencyConnector

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.services.files import FileService

from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from journalio.models import JournalEntry, JournalEntryConnector
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService

from supplierio.django_rest.serializers.common import PrivateSupplierSlimSerializer
from supplierio.models import Supplier


from tagio.choices import TagStatusChoices, TagKindChoices
from tagio.models import Tag, TagConnector

from purchaseio.choices import PayBillStatusChoices, PayBillItemStatusChoices
from purchaseio.models import PayBill, PayBillItem

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

class PrivateWePayBillListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    # Payee related
    payees = JSONField(required=False, write_only=True)

    # Tag realted
    tag_title_list = JSONField(required=False, write_only=True)

    # Currency related
    currency = PrivateCurrencySlimSerializer(
        read_only=True, source="currencyconnector_set.first.currency"
    )
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=True, write_only=True
    )

    # File related
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)

    # Payment account related
    payment_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    payment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PayBill
        fields = [
            "uid",
            "date",
            "status",
            "tax_kind",
            "tracking_number",
            "total",
            "description",
            "payment_account",
            "tag_title_list",
            # Currency related
            "currency",
            "currency_rate",
            "currency_kind",
            # File related fields
            "files",
            "file_description",
            "file_uids",
            # Payees
            "payees",
            "payment_account_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "payment_account"]

    def validate(self, validated_data):
        if not validated_data["payees"]:
            raise ValidationError({"message": "Please select payee."})
        if not validated_data.get("payment_account_uid"):
            raise ValidationError({"message": "Please select payment account."})
        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        validated_data["tracking_number"] = validated_data.get(
            "tracking_number",
            get_unique_id(PayBill, company.id, "tracking_number", "PAYBILL"),
        )
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
            ],
            company,
        )
        payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")

        payment_account = validated_data.pop("payment_account_uid", None)
        payees = validated_data.pop("payees", None)
        tag_title_list = validated_data.pop("tag_title_list", None)
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)

        # Create Paybill
        pay_bill = PayBill.objects.create(
            status=PayBillStatusChoices.PUBLISHED,
            payment_account=payment_account,  # Add payment_account here
            **validated_data,
        )

        # Create paybill items. Kept, and in payee order, because each one
        # now has to say which bills it paid.
        created_items = PayBillItem.objects.bulk_create(
            [
                PayBillItem(
                    pay_bill=pay_bill,
                    applied_credit=payee["applied_credit"],
                    total=payee["total"],
                    status=PayBillItemStatusChoices.PUBLISHED,
                    supplier=get_object_or_404(
                        Supplier.objects.selectable().filter(
                            uid=payee["supplier_uid"],
                            company=company,
                        )
                    ),
                )
                for payee in payees
            ]
        )

        # Create currency connector
        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=user.get_active_company(),
        )
        CurrencyConnector.objects.create(
            currency=currency,
            model_kind=CurrencyConnectorModelKind.PAY_BILL,
            pay_bill=pay_bill,
        )

        # Create tag connector
        if tag_title_list:
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.PAY_BILL,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        pay_bill=pay_bill,
                    )
                    for tag_item in tag_items
                ]
            )
        # Create file connector
        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.PAY_BILL,
                object=pay_bill,
            )

        # Update supplier balances
        for payee_index, payee in enumerate(payees):
            # One leg list per payee. It was declared once before the loop
            # while the connector call sits inside it, so each iteration wrote
            # the whole accumulated list again -- and a PayBill has a single
            # journal entry (`create_journal_entry` does `get_or_create` on the
            # document FK), so every payee lands on the same one. Two payees
            # produced six legs where there should be four, the first payee's
            # A/P and payment pair written twice.
            #
            # The duplicated pair is one debit and one credit, so the entry
            # still balanced and no write-time check could see it. Meanwhile
            # `update_opening_balance` ran correctly once per payee, so the
            # ledger and the stored balances drifted apart by exactly the first
            # payee's total.
            connector_data = []
            supplier = get_object_or_404(
                Supplier.objects.selectable().filter(
                    uid=payee["supplier_uid"],
                    company=company,
                )
            )
            # Paying a bill DEBITS accounts payable -- the debt goes down --
            # and CREDITS the account the money leaves. Both sides are fixed by
            # the transaction, and both accounts are user-chosen: A/P's kind
            # comes from an editable account type (the reason
            # `repair_control_account_types` exists at all), and the payment
            # account is any account on the chart, a credit card included.
            #
            # `"substraction"` gave the right side only while A/P was a
            # LIABILITY and the payment account an ASSET.
            payable_action = action_for_side(
                payable_charter_account.kind,
                JournalEntryConnectorKindChoices.DEBIT,
            )
            payment_action = (
                action_for_side(
                    payment_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                if payment_account
                else None
            )

            # Updating supplier opening balance. The supplier is not a
            # ChartOfAccount and has no `kind`, so its move stays explicit.
            update_opening_balance(supplier, "debit", payee["total"], 0)
            update_opening_balance(
                payable_charter_account,
                balance_operation_for_action(payable_action),
                payee["total"],
                0,
            )
            # Update payment account opening balance
            if payment_account:
                update_opening_balance(
                    payment_account,
                    balance_operation_for_action(payment_action),
                    payee["total"],
                    0,
                )

            # Tagged with the payee line. One PayBill has ONE journal entry --
            # `create_journal_entry` does `get_or_create` on the document FK --
            # so every payee's legs land on the same entry, and without the tag
            # a single payee line cannot be unwound from it. `supplier` alone is
            # ambiguous the moment the same vendor appears twice.
            payee_legs = (None, None, None, None, created_items[payee_index])

            connector_data.append(
                (
                    payable_charter_account,
                    payable_action,
                    payee["total"],
                    payable_charter_account.opening_balance,
                    *payee_legs,
                )
            )

            if payment_account:
                connector_data.append(
                    (
                        payment_account,
                        payment_action,
                        payee["total"],
                        payment_account.opening_balance,
                        *payee_legs,
                    )
                )

            # Pay the bills down. Without this the payment relieved A/P and
            # the vendor balance and left every bill it paid at full value, so
            # the balance sheet fell while the A/P ageing report did not --
            # `SUPPLIER_GAPS.md` D6, and a divergence our own report docstring
            # documented as expected behaviour.
            #
            # Anything beyond the vendor's open bills is a prepayment, not an
            # error: `supplier.opening_balance` already carries it and there is
            # simply no bill for that part to name.
            apply_pay_bill_item(
                created_items[payee_index],
                payee["total"],
                allocations=resolve_bill_allocations(payee, supplier, company),
            )

            journal_entry = JournalEntryService.create_journal_entry(
                amount=payee["total"],
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.PAY_BILL,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=pay_bill,
            )

            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=payee["total"],
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                supplier=supplier,
                created_by=user.get_employee(),
            )

        return pay_bill


class PrivateWePayBillDetailsSerializer(ModelSerializer):
    # Tag related
    tag_title_list = JSONField(required=False, write_only=True)

    # Currency related
    currency = PrivateCurrencySlimSerializer(
        read_only=True, source="currencyconnector_set.first.currency"
    )
    currency_kind = ChoiceField(
        choices=CurrencyChoices.choices, required=False, write_only=True
    )
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=False, write_only=True
    )

    # File related
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)

    # Payment account related
    payment_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    payment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PayBill
        fields = [
            "uid",
            "date",
            "status",
            "tax_kind",
            "tracking_number",
            "total",
            "description",
            "payment_account",
            "tag_title_list",
            # Currency related
            "currency",
            "currency_rate",
            "currency_kind",
            # File related fields
            "files",
            "file_description",
            "file_uids",
            "payment_account_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "payment_account"]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company
        old_payment_account = instance.payment_account

        if payment_account_uid := validated_data.pop("payment_account_uid", None):
            validated_data["payment_account"] = payment_account_uid

        # Extract non-database fields
        tag_title_list = validated_data.pop("tag_title_list", None)
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)

        # Create currency connector
        if currency_kind or currency_rate:
            currency, _ = Currency.objects.get_or_create(
                kind=currency_kind,
                exchange_rate=currency_rate,
                company=user.get_active_company(),
            )
            CurrencyConnector.objects.create(
                currency=currency,
                model_kind=CurrencyConnectorModelKind.PAY_BILL,
                pay_bill=instance,
            )

        # Create tag connector
        if tag_title_list:
            Tag.objects.filter(
                id__in=TagConnector.objects.filter(pay_bill=instance).values_list(
                    "tag_id", flat=True
                )
            ).delete()

            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.PAY_BILL,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        pay_bill=instance,
                    )
                    for tag_item in tag_items
                ]
            )

        # Create file connector
        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.PAY_BILL,
                object=instance,
            )

        # Get new payment account after potential update and set flag for payment account change
        new_payment_account = validated_data.get("payment_account", old_payment_account)

        # Process updates if payment account changed
        if old_payment_account != new_payment_account:
            # The only path in the codebase that REPOINTS an existing leg to a
            # different account (`:529-534`). A ticked leg would silently move
            # to another bank while still carrying `reconciliation_id`, so the
            # closed session would hold a cleared line that is not even on the
            # account it reconciled.
            assert_not_reconciled(
                JournalEntry.objects.filter(
                    pay_bill=instance,
                    kind=JournalEntryKindChoices.PAY_BILL,
                    status=JournalEntryStatusChoices.PUBLISHED,
                ),
                action="change",
            )

            # Get all pay bill items
            pay_bill_items = PayBillItem.objects.filter(pay_bill=instance)

            for pay_bill_item in pay_bill_items:
                supplier = pay_bill_item.supplier
                amount = pay_bill_item.total

                journal_entries = JournalEntry.objects.filter(
                    pay_bill=instance,
                    kind=JournalEntryKindChoices.PAY_BILL,
                    status=JournalEntryStatusChoices.PUBLISHED,
                    journalentryconnector__supplier=supplier,
                ).distinct()

                for journal_entry in journal_entries:
                    journal_entry_items = journal_entry.journalentryconnector_set.all()

                    old_payment_journal_item = journal_entry_items.filter(
                        account=old_payment_account
                    ).first()

                    if old_payment_journal_item and new_payment_account:
                        old_payment_journal_item.account = new_payment_account
                        old_payment_journal_item.last_balance = (
                            new_payment_account.opening_balance
                        )
                        old_payment_journal_item.save_dirty_fields()

                    if old_payment_account:
                        # Repointing the payment: give the money back to the
                        # account it no longer comes from, take it from the one
                        # it now does. Derived from the same rule the posting
                        # uses rather than assumed, so a credit-card payment
                        # account unwinds the way it was posted -- these were
                        # hard-coded add/subtract, which mirrored the create
                        # leg only while both accounts were assets.
                        #
                        # (The old comments here said "Subtract from old" and
                        # "Add to new", which is backwards from what the code
                        # did and from what is correct.)
                        undo_old = inverse_balance_operation(
                            balance_operation_for_action(
                                action_for_side(
                                    old_payment_account.kind,
                                    JournalEntryConnectorKindChoices.CREDIT,
                                )
                            )
                        )
                        update_opening_balance(
                            old_payment_account, undo_old, amount, 0
                        )

                        update_opening_balance(
                            new_payment_account,
                            balance_operation_for_action(
                                action_for_side(
                                    new_payment_account.kind,
                                    JournalEntryConnectorKindChoices.CREDIT,
                                )
                            ),
                            amount,
                            0,
                        )

        return super().update(instance, validated_data)


class PrivateWePayBillItemListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    # Supplier related
    supplier = PrivateSupplierSlimSerializer(read_only=True, required=False)
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PayBillItem
        fields = [
            "uid",
            "status",
            "applied_credit",
            "total",
            # Supplier related
            "supplier",
            "supplier_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "supplier"]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        supplier = validated_data.pop("supplier_uid", None)
        validated_data["supplier"] = supplier
        validated_data["total"] = validated_data.get("total", 0)
        amount = validated_data["total"]
        pay_bill = get_object_or_404(
            PayBill.objects.filter(uid=self.context.get("uid"), company=company)
        )
        validated_data["pay_bill"] = pay_bill

        # Create the pay bill item
        pay_bill_item = super().create(validated_data)

        # Same rule as the list serializer: a payment pays bills down.
        apply_pay_bill_item(
            pay_bill_item,
            amount,
            allocations=resolve_bill_allocations(
                self.initial_data, supplier, company
            ),
        )

        connector_data = []
        payment_account = pay_bill.payment_account

        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
            ],
            company,
        )
        payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")

        # Same rule as the list serializer above: pay down the payable, credit
        # whatever the money leaves.
        payable_action = action_for_side(
            payable_charter_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        item_legs = (None, None, None, None, pay_bill_item)

        connector_data.append(
            (
                payable_charter_account,
                payable_action,
                amount,
                payable_charter_account.opening_balance,
                *item_legs,
            )
        )
        # Update opening balances. The supplier is not a ChartOfAccount.
        update_opening_balance(supplier, "debit", amount, 0)
        update_opening_balance(
            payable_charter_account,
            balance_operation_for_action(payable_action),
            amount,
            0,
        )

        # Add connector data for payment account
        if payment_account:
            payment_action = action_for_side(
                payment_account.kind, JournalEntryConnectorKindChoices.CREDIT
            )
            connector_data.append(
                (
                    payment_account,
                    payment_action,
                    amount,
                    payment_account.opening_balance,
                    *item_legs,
                )
            )
            update_opening_balance(
                payment_account,
                balance_operation_for_action(payment_action),
                amount,
                0,
            )

        # Create journal entry
        journal_entry = JournalEntryService.create_journal_entry(
            amount=amount,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.PAY_BILL,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=pay_bill,
        )

        # Create journal entry connectors
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=amount,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            supplier=supplier,
            created_by=user.get_employee(),
        )

        return pay_bill_item


class PrivateWePayBillItemDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    supplier = PrivateSupplierSlimSerializer(read_only=True, required=False)
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PayBillItem
        fields = [
            "uid",
            "status",
            "applied_credit",
            "total",
            "supplier",
            "supplier_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "supplier"]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()

        if supplier_uid := validated_data.pop("supplier_uid", None):
            validated_data["supplier"] = supplier_uid

        old_total = instance.total
        new_total = validated_data.get("total", old_total)

        if old_total != new_total and instance.pay_bill:

            pay_bill = instance.pay_bill
            payment_account = pay_bill.payment_account
            supplier = instance.supplier

            # Before `unapply_pay_bill_item` below, which is the first statement
            # that changes anything. Gated on the total having moved, because a
            # payee line edited without a total change rewrites no leg.
            assert_not_reconciled(
                JournalEntry.objects.filter(
                    pay_bill=pay_bill,
                    kind=JournalEntryKindChoices.PAY_BILL,
                    status=JournalEntryStatusChoices.PUBLISHED,
                ),
                action="change",
            )

            # Take the old payment back off the bills, then pay the new figure
            # down. Two steps rather than a delta because the applications name
            # the bills and the amounts: lowering a payment has to give back to
            # exactly what it took from, and by the time it is amended those
            # bills may have moved for other reasons. The mirror rule, applied
            # to a subledger column instead of a journal leg.
            unapply_pay_bill_item(instance)
            apply_pay_bill_item(instance, new_total)

            # Get accounts payable chart of account
            chart_of_accounts = get_chart_of_account(
                ["Accounts Payable (A/P)"],
                company,
            )
            payable_chart_account = chart_of_accounts.get("Accounts Payable (A/P)")

            # Find the journal entry related to this pay bill item
            journal_entries = JournalEntry.objects.filter(
                pay_bill=pay_bill,
                kind=JournalEntryKindChoices.PAY_BILL,
                status=JournalEntryStatusChoices.PUBLISHED,
                journalentryconnector__supplier=supplier,
            ).distinct()

            for journal_entry in journal_entries:
                journal_entry_items = journal_entry.journalentryconnector_set.all()

                # Paying more extinguishes more of the debt; paying less
                # gives some back. Derived from the same rule the posting leg
                # uses, so the amend mirrors it for any account kind rather
                # than only while A/P is a liability.
                payable_apply = balance_operation_for_action(
                    action_for_side(
                        payable_chart_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                )
                if new_total > old_total:
                    difference = new_total - old_total
                    update_opening_balance(supplier, "debit", difference, 0)
                    update_opening_balance(
                        payable_chart_account, payable_apply, difference, 0
                    )
                else:
                    difference = old_total - new_total
                    update_opening_balance(
                        supplier, "credit", difference, 0
                    )
                    update_opening_balance(
                        payable_chart_account,
                        inverse_balance_operation(payable_apply),
                        difference,
                        0,
                    )

                journal_entry.amount = new_total
                journal_entry.save_dirty_fields()

                payable_connector = journal_entry_items.filter(
                    account=payable_chart_account
                ).first()

                if payable_connector:
                    if payable_connector.kind == JournalEntryConnectorKindChoices.DEBIT:
                        payable_connector.debit = new_total
                    else:
                        payable_connector.credit = new_total

                    payable_connector.total = new_total
                    payable_connector.last_balance = (
                        payable_chart_account.opening_balance
                    )
                    payable_connector.save_dirty_fields()

                if payment_account:
                    payment_apply = balance_operation_for_action(
                        action_for_side(
                            payment_account.kind,
                            JournalEntryConnectorKindChoices.CREDIT,
                        )
                    )
                    if new_total > old_total:
                        difference = new_total - old_total
                        update_opening_balance(
                            payment_account,
                            payment_apply,
                            difference,
                            0,
                        )
                    else:
                        difference = old_total - new_total
                        update_opening_balance(
                            payment_account,
                            inverse_balance_operation(payment_apply),
                            difference,
                            0,
                        )

                    payment_connector = journal_entry_items.filter(
                        account=payment_account
                    ).first()

                    if payment_connector:
                        if (
                            payment_connector.kind
                            == JournalEntryConnectorKindChoices.DEBIT
                        ):
                            payment_connector.debit = new_total
                        else:
                            payment_connector.credit = new_total

                        payment_connector.total = new_total
                        payment_connector.last_balance = payment_account.opening_balance
                        payment_connector.save_dirty_fields()

        return super().update(instance, validated_data)
