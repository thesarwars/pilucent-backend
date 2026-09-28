import logging
from decimal import Decimal

from rest_framework.serializers import (
    BooleanField,
    ModelSerializer,
    SlugRelatedField,
    CharField,
    ChoiceField,
    FileField,
    ListField,
    JSONField,
    DecimalField,
)
from rest_framework.generics import get_object_or_404

from django.db import transaction

from weapi.django_rest.helpers.credit_note_posting import (
    record_credit_note_movement,
)
from weapi.django_rest.helpers.purchase_item_helpers import (
    get_latest_published_purchase_item,
)

from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices
from addressio.django_rest.serializers.common import PrivateAddressSerializer

from agencyio.django_rest.serializers.common import PrivateAgencyTaxSlimSerializer
from agencyio.models import AgencyTax

from accounts.choices import ChartOfAccountStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from accounts.models import ChartOfAccount

from categoryio.django_rest.serializers.common import PrivateCategorySlimSerializer

from common.choices import CurrencyChoices
from common.django_rest.helpers.serializer_scoping import company_scoped
from common.django_rest.helpers.retire_guard import assert_not_retiring_by_patch
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.quantity_helpers import update_quantity
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    amend_balance,
    amend_leg,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.file_helpers import (
    get_pdf,
    file_url,
    link_file_to,
)
from common.django_rest.helpers.emails import send_email_to_user

from creditnoteio.models import CreditNote, CreditNoteItem
from creditnoteio.choices import CreditNoteItemStatusChoices, CreditNoteKindChoices

from customerio.models import Customer
from customerio.choices import CustomerStatusChoices
from customerio.django_rest.serializers.common import (
    PrivateCustomerSlimSerializer,
)
from currencyio.django_rest.serializers.common import PrivateCurrencySlimSerializer
from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.services.files import FileService

from journalio.django_rest.services.journals import JournalEntryService
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.models import JournalEntry

from productio.models import Product
from productio.django_rest.serializers.common import PrivateProductSlimSerializer

from supplierio.django_rest.serializers.common import (
    PrivateSupplierSlimSerializer,
)
from supplierio.models import Supplier

from tagio.choices import TagStatusChoices, TagKindChoices
from tagio.models import Tag, TagConnector

from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer
from wirehouseio.models import Warehouse

logger = logging.getLogger(__name__)


def post_unattributed_tax(credit_note, company, posted, tax_side, connector_data):
    """Post tax the credit note declares that its own legs did not account for.

    The mirror of `sale_posting._post_unattributed_tax`, and it exists for the
    same reason on the other side of the transaction. `total_tax` is a header
    figure the client sends; the liability legs come from somewhere else -- the
    per-item tax rates, or the `credit_note_sales_tax` breakdown. A note
    carrying `total_tax` with neither produced no tax leg at all, so the
    receivable was credited for the tax-inclusive amount and nothing debited the
    liability back. The entry was short by exactly `total_tax`.

    That is 30 of the 42 credit notes on production -- a 71% failure rate, the
    worst of any document kind.

    Posts the SHORTFALL, not the whole declared total, so a note whose legs
    partly account for the header tops up only the difference. Where the header
    and the detail disagree, it balances the entry AND warns: an unbalanced
    entry is a worse way to keep a fault visible than a balanced entry plus a
    warning. Same conclusion the sale side reached, for the same reason.
    """
    declared = Decimal(str(credit_note.total_tax or 0))
    if not declared:
        return

    residual = declared - posted
    if abs(residual) <= Decimal("0.01"):
        # The legs account for the header, give or take rounding.
        return

    if posted:
        logger.warning(
            "credit note %s: declares total_tax %s but its tax legs total %s. "
            "The header disagrees with its own detail.",
            credit_note.pk, declared, posted,
        )

    if residual < 0:
        logger.error(
            "credit note %s: tax legs total %s, MORE than the declared "
            "total_tax %s. Refusing to post a negative leg, so this entry will "
            "not balance -- the note's own tax detail needs correcting.",
            credit_note.pk, posted, declared,
        )
        return

    account = get_chart_of_account(["Sales Tax Payable"], company).get(
        "Sales Tax Payable"
    )
    if account is None:
        logger.error(
            "credit note %s: %s of declared tax is unaccounted for and company "
            "%s has no Sales Tax Payable account to post it to. The entry will "
            "not balance.",
            credit_note.pk, residual, getattr(company, "pk", company),
        )
        return

    logger.info(
        "credit note %s: %s of the declared total_tax %s reached no agency "
        "account -- posting the shortfall to Sales Tax Payable so the entry "
        "balances",
        credit_note.pk, residual, declared,
    )
    action = action_for_side(account.kind, tax_side)
    update_opening_balance(
        account, balance_operation_for_action(action), residual, 0
    )
    connector_data.append(
        (account, action, residual, account.opening_balance, None)
    )


def append_product_reversal_legs(
    connector_data,
    *,
    income_account,
    asset_account,
    cogs_account,
    total_income,
    total_cost,
    item,
    company=None,
):
    """Legs that unwind one product line of a SALE credit note.

    Two gates, because there are two independent questions.

    **Revenue** reverses on the strength of the line's income alone. It used to
    sit inside `if total_cost_of_good != 0`, so a line whose cost resolved to
    zero credited the receivable back and never debited the revenue: company
    114's journal 1434 is short by exactly its 550 of income, while journal
    1439 -- the same document shape with a non-zero cost -- balances to within
    rounding.

    **The cost pair** -- inventory back in, cost of sales out -- is sized by the
    line's cost and posts together or not at all. A zero-cost line genuinely has
    no cost to reverse.

    The balance moves live inside their own gate rather than above both, which
    is the other half of the same defect: on those documents the income
    account's stored balance moved by the revenue while the journal recorded
    nothing, so the two drifted apart by construction.

    This lives outside the serializers because it was duplicated between
    `create` and the item-level path, and the duplicate is why the gate was
    wrong in two places at once.
    """
    if total_income and income_account is None and company is not None:
        # A product with no `income_account` reversed the receivable and debited
        # revenue nowhere -- the entry short by the whole line. The revenue was
        # recognised somewhere when the invoice was raised, so there is always a
        # correct place to hand it back; `resolve_cogs_account` reaches for the
        # COGS control account in exactly this situation, and this is its
        # revenue-side twin. SALES_OF_PRODUCT_INCOME is seeded on 60 of 60
        # companies.
        income_account = get_chart_of_account(
            ["Sales of Product Income"], company
        ).get("Sales of Product Income")

    if total_income and income_account:
        update_opening_balance(income_account, "debit", total_income, 0)
        connector_data.append(
            (
                income_account,
                "substraction",
                total_income,
                income_account.opening_balance,
                None,
                None,
                None,
                item,
            )
        )
    elif total_income:
        # Nothing to reverse against, and the receivable has already been
        # credited back. Say so rather than shipping a short entry silently.
        logger.error(
            "credit note: %s of revenue on a line cannot be reversed -- the "
            "product has no income account and no Sales of Product Income "
            "control account was found. The entry will not balance.",
            total_income,
        )

    if not total_cost:
        return connector_data

    if cogs_account:
        # Connector "substraction" is CREDIT on an expense -- cost reduced --
        # and `balance_operation_for_action` pairs that with "debit", subtract.
        update_opening_balance(cogs_account, "debit", total_cost, 0)
    if asset_account:
        # The inventory leg is the odd one out and was mispaired. Its connector
        # is "addition", which on an asset is a DEBIT -- goods coming back, so
        # inventory goes UP -- and the matching balance operation is therefore
        # "credit", add. It said "debit", subtract, so the journal moved
        # inventory up while the stored balance moved it down, leaving the two
        # apart by twice the cost on every costed credit note.
        #
        # The income and cost legs beside it were already paired correctly.
        # 7c36c73f lifted all three into this helper and fixed which gate each
        # sits behind without checking the directions it carried across.
        update_opening_balance(asset_account, "credit", total_cost, 0)

    if asset_account:
        connector_data.append(
            (
                asset_account,
                "addition",
                total_cost,
                asset_account.opening_balance,
                None,
                None,
                None,
                item,
            )
        )
    if cogs_account:
        connector_data.append(
            (
                cogs_account,
                "substraction",
                total_cost,
                cogs_account.opening_balance,
                None,
                None,
                None,
                item,
            )
        )
    return connector_data

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

class PrivateWeCreditNoteListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    customer = PrivateCustomerSlimSerializer(read_only=True)
    customer_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Customer.objects.selectable().all().exclude(status=CustomerStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )
    # Currency related
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True, required=False)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, write_only=True, required=False
    )
    tag_title_list = JSONField(write_only=True, required=False)
    full_address = CharField(write_only=True, required=False)
    warehouse_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Warehouse.objects.all(),
        write_only=True,
        required=False,
    )
    credit_note_items = JSONField(required=False, write_only=True)
    custom_expense_items = JSONField(required=False, write_only=True)
    credit_note_sales_tax = JSONField(required=False, write_only=True)
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)

    sale_remaining_balance = DecimalField(
        source="get_sale_remaining_balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    purchase_remaining_balance = DecimalField(
        source="get_purchase_remaining_balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    is_fully_used_sale = BooleanField(read_only=True, source="get_is_fully_used_sale")
    is_fully_used_purchase = BooleanField(
        read_only=True, source="get_is_fully_used_purchase"
    )

    class Meta:
        model = CreditNote
        fields = [
            "uid",
            "date",
            "email",
            "credit_note_number",
            "customer",
            "customer_uid",
            "supplier",
            "supplier_uid",
            "kind",
            "status",
            "tax_kind",
            "description",
            "total",
            "sale_remaining_balance",
            "purchase_remaining_balance",
            "is_fully_used_sale",
            "is_fully_used_purchase",
            "tag_title_list",
            "full_address",
            "warehouse_uid",
            "credit_note_items",
            "custom_expense_items",
            "credit_note_sales_tax",
            "files",
            "file_description",
            "file_uids",
            # Crurrency related
            "currency_kind",
            "currency_rate",
            # Tax related
            "total_tax",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "remaining_balance",
            "created_by",
            "company",
            "created_at",
            "updated_at",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        company = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company
        customer = validated_data.pop("customer_uid", None)
        validated_data["customer"] = customer
        validated_data["warehouse"] = validated_data.pop("warehouse_uid", None)
        supplier = validated_data.pop("supplier_uid", None)
        validated_data["supplier"] = supplier
        total = validated_data["total"]
        total_tax = validated_data["total_tax"]
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", 1)
        tag_title_list = validated_data.pop("tag_title_list", None)
        full_address = validated_data.pop("full_address", None)
        credit_note_items = validated_data.pop("credit_note_items", None)
        custom_expense_items = validated_data.pop("custom_expense_items", None)
        credit_note_sales_tax_data = validated_data.pop("credit_note_sales_tax", None)
        logger.info("credit_note_sales_tax_data from serializer: %s", credit_note_sales_tax_data)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        validated_data["credit_note_number"] = validated_data.get(
            "credit_note_number",
            get_unique_id(CreditNote, company.id, "credit_note_number", "CN"),
        )
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Receivable (A/R)",
                "Accounts Payable (A/P)",
                "Sales Tax Payable",
                "Cost of Goods Sold (COGS)",
                "Inventory Asset",
            ],
            company,
        )
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        account_payable = chart_of_accounts.get("Accounts Payable (A/P)")
        payable_account = chart_of_accounts.get("Sales Tax Payable")
        inventory_account = chart_of_accounts.get("Inventory Asset")

        # emails
        email = validated_data.get("email", {})

        # Determine primary email based on customer or supplier
        primary_email = None
        if customer and customer.email:
            primary_email = customer.email
        elif supplier and supplier.email:
            primary_email = supplier.email

        customer_email = (
            email.get("customer_email", primary_email)
            if email and primary_email
            else primary_email or ""
        )
        emails = []
        if customer_email:
            emails.append(customer_email)
        emails += [email.get("cc_emails", "") if email else ""]
        emails += [email.get("bcc_emails", "") if email else ""]

        connector_data = []

        # Creating creditnote
        credit_note = CreditNote.objects.create(**validated_data)

        # Save credit_note_sales_tax JSON data if provided from frontend
        if credit_note_sales_tax_data:
            credit_note.credit_note_sales_tax = credit_note_sales_tax_data
            credit_note.save(update_fields=["credit_note_sales_tax"])

        if currency_kind and currency_rate:
            currency, _ = Currency.objects.get_or_create(
                kind=currency_kind,
                exchange_rate=currency_rate,
                company=user.get_active_company(),
            )

            CurrencyConnector.objects.create(
                currency=currency,
                model_kind=CurrencyConnectorModelKind.CREDIT_NOTE_ITEM,
                credit_note=credit_note,
            )

        if full_address:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_address, company=validated_data["company"]
                ),
                credit_note=credit_note,
                kind=AddressConnectorKindCoices.CREDIT_NOTE_ITEM,
            )

        if tag_title_list:
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.CREDIT_NOTE_ITEM,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        credit_note=credit_note,
                    )
                    for tag_item in tag_items
                ]
            )

        if custom_expense_items:
            CreditNoteItem.objects.bulk_create(
                [
                    CreditNoteItem(
                        credit_note=credit_note,
                        section=custom_expense_item.get("section", None),
                        note=custom_expense_item.get("note", None),
                        status=CreditNoteItemStatusChoices.ACTIVE,
                        description=custom_expense_item.get("description", None),
                        total=custom_expense_item.get("total", 0),
                        tax=(
                            get_object_or_404(
                                AgencyTax.objects.filter(
                                    uid=custom_expense_item.get("tax_uid"),
                                    company=company,
                                )
                            )
                            if custom_expense_item.get("tax_uid")
                            else None
                        ),
                        charter_account=get_object_or_404(
                            company_scoped(ChartOfAccount.objects.filter(
                                status=ChartOfAccountStatusChoices.ACTIVE,
                                uid=custom_expense_item.get(
                                    "charter_account_uid", None
                                ),
                            ), self)
                        ),
                        item_credit=custom_expense_item.get("item_credit", 0),
                    )
                    for custom_expense_item in custom_expense_items
                ]
            )
            if validated_data["kind"] == CreditNoteKindChoices.PURCHASE:
                for custom_expense_item in custom_expense_items:
                    charter_account = get_object_or_404(
                        company_scoped(ChartOfAccount.objects.filter(
                            uid=custom_expense_item.get("charter_account_uid", None)
                        ), self)
                    )
                    item_expense_total = Decimal(custom_expense_item["total"])

                    # Directly update the opening balance for each expense item's charter account
                    if item_expense_total != 0:
                        update_opening_balance(
                            charter_account,
                            JournalEntryConnectorKindChoices.DEBIT,
                            item_expense_total,
                            0,
                        )
                        custom_item = CreditNoteItem.objects.filter(
                            credit_note=credit_note,
                            charter_account=charter_account,
                            total=item_expense_total,
                        ).first()

                        connector_data.append(
                            (
                                charter_account,
                                "substraction",
                                item_expense_total,
                                charter_account.opening_balance,
                                None,
                                None,
                                None,
                                custom_item,
                            )
                        )

        if credit_note_items:
            credit_notes = []
            for credit_note_item in credit_note_items:
                product = get_object_or_404(
                    company_scoped(Product.objects.filter(uid=credit_note_item.get("product_uid")), self)
                )
                
                quantity = int(credit_note_item.get("quantity", 0))
                product_income_account = product.income_account
                product_asset_account = product.asset_account

                # Create a single CreditNoteItem object and save it immediately
                new_item = CreditNoteItem(
                    credit_note=credit_note,
                    section=credit_note_item.get("section", None),
                    note=credit_note_item.get("note", None),
                    status=CreditNoteItemStatusChoices.ACTIVE,
                    description=credit_note_item.get("description", None),
                    quantity=quantity,
                    total=credit_note_item.get("total", 0),
                    tax=(
                        get_object_or_404(
                            AgencyTax.objects.filter(
                                uid=credit_note_item.get("tax_uid"),
                                company=company,
                            )
                        )
                        if credit_note_item.get("tax_uid")
                        else None
                    ),
                    product=product,
                    item_credit=credit_note_item.get("item_credit", 0),
                )
                new_item.save()  # Save immediately to get an ID
                credit_notes.append(new_item)

                if validated_data["kind"] == CreditNoteKindChoices.SALE:
                    quantity = int(credit_note_item.get("quantity", 0))

                    credit_note_date = validated_data.get("date")
                    total_income_balance = Decimal(credit_note_item.get("total", 0))
                    credit_cost = Decimal(0)

                    update_quantity(product, "addition", quantity, 0)

                    # Try to get the latest purchase item first
                    purchase_item = get_latest_published_purchase_item(
                        product=product, company=company, date=credit_note_date
                    )

                    unit_price = 0
                    product_additional_cost = product.productadditionalcost_set.first()
                    if purchase_item and purchase_item.purchase_price:
                        unit_price = purchase_item.purchase_price
                    elif product_additional_cost and product_additional_cost.amount:
                        unit_price = product_additional_cost.amount

                    # This LINE's cost. A running total used to be accumulated
                    # here and passed to `append_product_reversal_legs` below,
                    # inside this same loop, so line 1 posted its own cost, line 2
                    # posted lines 1+2, and line n posted lines 1..n. A three-line
                    # note with costs 10/20/30 relieved 100 of inventory instead
                    # of 60.
                    #
                    # It balanced throughout -- the cost posts as a pair, an
                    # inventory debit against a cost-of-sales credit of the same
                    # figure -- so both sides were overstated equally and nothing
                    # could see it. The accumulator had no other consumer, so it
                    # is gone rather than left looking purposeful.
                    credit_cost = unit_price * quantity

                    record_credit_note_movement(
                        credit_note, new_item, product, quantity,
                        inbound=True, unit_price=unit_price,
                    )

                    # If purchase item exists, update its quantities
                    if purchase_item:
                        purchase_item.quantity += quantity
                        purchase_item.opening_quantity += quantity
                        purchase_item.save()

                    # Get the cost_of_good_sold_account
                    cost_of_good_sold_account = (
                        product_additional_cost.expense_account
                        if product_additional_cost
                        else None
                    )
                    logger.info("Cost of Good Sold Account for product %s: %s", cost_of_good_sold_account)
                    logger.info("Product asset account for product %s: %s", product_asset_account)
                    logger.info("Product income account for product %s: %s", product_income_account)
                    append_product_reversal_legs(
                        connector_data,
                        income_account=product_income_account,
                        asset_account=product_asset_account,
                        cogs_account=cost_of_good_sold_account,
                        total_income=total_income_balance,
                        total_cost=credit_cost,
                        item=new_item,
                        company=company,
                    )

                elif validated_data["kind"] == CreditNoteKindChoices.PURCHASE:
                    update_quantity(product, "deduction", quantity, 0)

                    total_product_balance = Decimal(credit_note_item.get("total", 0))

                    record_credit_note_movement(
                        credit_note, new_item, product, quantity,
                        inbound=False,
                        unit_price=(
                            total_product_balance / quantity if quantity else None
                        ),
                    )

                    # Goods going back to the supplier CREDIT inventory. The
                    # connector already recorded that credit, but the balance
                    # move beside it passed CREDIT to `update_opening_balance`,
                    # whose CREDIT means ADD -- not an accounting side. So the
                    # ledger lowered inventory while the stored balance raised
                    # it, leaving the two out by twice the line, with a journal
                    # entry that still balanced.
                    inventory_action = action_for_side(
                        inventory_account.kind,
                        JournalEntryConnectorKindChoices.CREDIT,
                    )
                    update_opening_balance(
                        inventory_account,
                        balance_operation_for_action(inventory_action),
                        total_product_balance,
                        0,
                    )
                    if total_product_balance != 0:
                        connector_data.append(
                            (
                                inventory_account,
                                inventory_action,
                                total_product_balance,
                                inventory_account.opening_balance,
                                None,
                                None,
                                None,
                                new_item,
                            )
                        )

        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.CREDIT_NOTE,
                object=credit_note,
            )
        # Creating journal entry
        journal_entry = JournalEntryService.create_journal_entry(
            amount=validated_data["total"],
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.CREDIT_NOTE,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=credit_note,
        )
        if validated_data["kind"] == CreditNoteKindChoices.SALE:
            # Updating customer opening balance
            update_opening_balance(customer, "debit", total, 0)

            # Receivable amount
            update_opening_balance(
                receivable_account,
                "debit",
                total,
                0,
            )

            if total != 0:
                connector_data.append(
                    (
                        receivable_account,
                        "substraction",
                        total,
                        receivable_account.opening_balance,
                        None,
                    )
                )

            # What the tax legs below actually account for, so the shortfall
            # against the declared header can be posted once at the end.
            posted_tax = Decimal("0")

            # Payable amount — per-item tax from credit_note_items
            if credit_note_items:
                for credit_note_item in credit_note_items:
                    is_tax = credit_note_item.get("is_tax", credit_note_item.get("is_item_tax", False))
                    tax_uid = credit_note_item.get("tax_uid")
                    if not is_tax or not tax_uid:
                        continue

                    item_total = Decimal(credit_note_item.get("total", 0))
                    # Company-scoped: this walks `item_tax.tax_groups` straight
                    # to `tax_group.sales_tax_account` and posts to it, so an
                    # unscoped lookup here books tax into another tenant's
                    # liability account, not merely leaks their rate.
                    item_tax = get_object_or_404(
                        AgencyTax.objects.filter(uid=tax_uid, company=company)
                    )
                    for tax_group in item_tax.tax_groups.all():
                        item_payable_account = tax_group.sales_tax_account
                        tax_amount = item_total * (tax_group.rate / 100)
                        # Handing tax back DEBITS the liability. "credit" here
                        # meant ADD, so the liability grew in the stored balance
                        # while the journal reversed it.
                        #
                        # The balance also moved unconditionally while its
                        # journal line was gated on the document's `total_tax`,
                        # so a credit note carrying per-item tax but a zero
                        # header total moved the liability with nothing in the
                        # ledger to explain it. Both are gated together now.
                        item_tax_action = action_for_side(
                            item_payable_account.kind,
                            JournalEntryConnectorKindChoices.DEBIT,
                        )
                        if tax_amount != 0:
                            update_opening_balance(
                                item_payable_account,
                                balance_operation_for_action(item_tax_action),
                                tax_amount,
                                0,
                            )
                            connector_data.append(
                                (
                                    item_payable_account,
                                    item_tax_action,
                                    tax_amount,
                                    item_payable_account.opening_balance,
                                    None,
                                )
                            )
                            posted_tax += tax_amount

            # Handle credit_note_sales_tax breakdown if provided
            if credit_note_sales_tax_data and credit_note_sales_tax_data.get("breakdown"):
                logger.info("Processing credit_note_sales_tax for SALE: %s", credit_note_sales_tax_data)
                breakdown = credit_note_sales_tax_data.get("breakdown", {})
                account_titles = list(breakdown.keys())
                breakdown_chart_of_accounts = get_chart_of_account(account_titles, company)
                logger.info("SALE credit_note_sales_tax: account_titles=%s, chart_of_accounts=%s", account_titles, breakdown_chart_of_accounts)

                for account_title, breakdown_data in breakdown.items():
                    tax_amount = Decimal(str(breakdown_data.get("amount", 0)))
                    breakdown_payable_account = breakdown_chart_of_accounts.get(account_title)
                    logger.info("SALE credit_note_sales_tax: account_title=%s, tax_amount=%s, payable_account=%s", account_title, tax_amount, breakdown_payable_account)

                    if breakdown_payable_account:
                        if tax_amount > 0:
                            # Same pair as the per-item legs above: DEBIT the
                            # liability, and move the balance the matching way.
                            breakdown_tax_action = action_for_side(
                                breakdown_payable_account.kind,
                                JournalEntryConnectorKindChoices.DEBIT,
                            )
                            update_opening_balance(
                                breakdown_payable_account,
                                balance_operation_for_action(breakdown_tax_action),
                                tax_amount,
                                0,
                            )
                            connector_data.append(
                                (
                                    breakdown_payable_account,
                                    breakdown_tax_action,
                                    tax_amount,
                                    breakdown_payable_account.opening_balance,
                                    None,
                                )
                            )
                            posted_tax += tax_amount
                            logger.info("SALE credit_note_sales_tax: added connector_data for %s, substraction, %s", breakdown_payable_account.title, tax_amount)
                    else:
                        logger.warning("SALE credit_note_sales_tax: chart of account not found for title=%s", account_title)
                        continue
                logger.info("SALE credit_note_sales_tax complete: total connector_data entries=%s", len(connector_data))

            # Whatever the header declares and the legs above did not reach.
            # Covers all three ways this went short: a note with no per-item tax
            # flags at all, a rate that disagrees with the header, and a
            # breakdown whose account no longer exists.
            post_unattributed_tax(
                credit_note,
                company,
                posted_tax,
                JournalEntryConnectorKindChoices.DEBIT,
                connector_data,
            )

        if validated_data["kind"] == CreditNoteKindChoices.PURCHASE:
            # Updating supplier opening balance
            update_opening_balance(
                supplier, JournalEntryConnectorKindChoices.DEBIT, total, 0
            )

            # Payable amount
            update_opening_balance(
                account_payable,
                JournalEntryConnectorKindChoices.DEBIT,
                total,
                0,
            )

            if total != 0:
                connector_data.append(
                    (
                        account_payable,
                        "substraction",
                        total,
                        account_payable.opening_balance,
                        None,
                    )
                )

            # The bill DEBITED this account -- a purchase's tax is always a
            # debit, because the cost lines carry only the net -- so the vendor
            # credit that reverses it must CREDIT it. "substraction" is a DEBIT
            # on a liability: the same side as the bill, and the same side as
            # the A/P leg just above. The branch therefore posted debits of
            # `total + total_tax` against credits of `total - total_tax`, and
            # every taxed purchase credit note was out by exactly twice its tax.
            #
            # That the entry balances once this is a credit is itself the
            # evidence that `total` arrives gross: debits `total` against
            # credits of the net lines plus `total_tax`.
            #
            # The stale "# Receivable amount" comment was copied from the SALE
            # branch above, which is where the wrong side came from.
            purchase_tax_action = action_for_side(
                payable_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            if total_tax != 0:
                update_opening_balance(
                    payable_account,
                    balance_operation_for_action(purchase_tax_action),
                    total_tax,
                    0,
                )
                connector_data.append(
                    (
                        payable_account,
                        purchase_tax_action,
                        total_tax,
                        payable_account.opening_balance,
                        None,
                    )
                )

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            customer=(
                customer
                if validated_data["kind"] == CreditNoteKindChoices.SALE
                else None
            ),
            supplier=(
                supplier
                if validated_data["kind"] == CreditNoteKindChoices.PURCHASE
                else None
            ),
            created_by=user.get_employee(),
        )

        # Email sending
        title = "CREDIT NOTE"
        subject = f"Balanzify {title}"
        credit_note_pdf = get_pdf(
            self,
            False,
            {
                "label": "credit_notes",
                "template": "emails/credit_notes/credit_note_pdf_template.html",
                "title": title,
                "is_report": False,
                "data": {
                    "company": company,
                    "customer": customer,
                    "full_address": full_address,
                    "customer_email": customer_email,
                    "credit_note": credit_note,
                    "credit_note_items": credit_note.creditnoteitem_set.all(),
                },
            },
        )
        send_email_to_user(
            {
                "title": title,
                "company": company,
                "customer": customer,
                "url": file_url(credit_note_pdf.file, request),
            },
            "emails/sale_payments/payment_receive_email_template.html",
            emails,
            subject,
        )
        return validated_data


class PrivateWeCreditNoteDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    warehouse = PrivateWarehouseSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    currency = PrivateCurrencySlimSerializer(
        read_only=True, source="currencyconnector_set.first.currency"
    )

    address = PrivateAddressSerializer(
        source="addressconnector_set.first.address",
        read_only=True,
    )
    customer_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Customer.objects.selectable().all().exclude(status=CustomerStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=True, write_only=True
    )
    tag_title_list = JSONField(write_only=True, required=False)
    full_address = CharField(write_only=True, required=False)
    warehouse_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Warehouse.objects.all(),
        write_only=True,
        required=False,
    )
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)
    remaining_balance = DecimalField(
        source="get_remaining_balance", max_digits=10, decimal_places=2, read_only=True
    )
    is_fully_used = BooleanField(read_only=True, source="get_is_fully_used")

    class Meta:
        model = CreditNote
        fields = [
            "uid",
            "date",
            "email",
            "credit_note_number",
            "customer",
            "customer_uid",
            "supplier",
            "supplier_uid",
            "kind",
            "status",
            "tax_kind",
            "description",
            "total",
            "remaining_balance",
            "is_fully_used",
            # Currency related
            "currency",
            "currency_kind",
            "currency_rate",
            "tag_title_list",
            "full_address",
            "address",
            "warehouse_uid",
            "warehouse",
            "files",
            "file_description",
            "file_uids",
            # Tax related
            "total_tax",
            "created_by",
        ]

    read_only_fields = ["uid", "created_by", "company"]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        # `status` is writable here and read-only on none of the six
        # detail serializers, so a PATCH could retire the document by
        # writing the column -- skipping every guard, the reversal and
        # the allocation unwind that live in `perform_destroy`.
        assert_not_retiring_by_patch(
            instance, validated_data, document='credit note',
        )

        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["customer"] = validated_data.pop(
            "customer_uid", instance.customer
        )
        validated_data["supplier"] = validated_data.pop(
            "supplier_uid", instance.supplier
        )
        validated_data["warehouse"] = validated_data.pop("warehouse_uid", None)
        validated_data["company"] = company
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        tag_titles = validated_data.pop("tag_title_list", None)
        full_address = validated_data.pop("full_address", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Receivable (A/R)",
                "Accounts Payable (A/P)",
                "Sales Tax Payable",
                "Cost of Goods Sold (COGS)",
            ],
            company,
        )
        journal_entry = JournalEntry.objects.filter(credit_note=instance).order_by("id").first()
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        account_payable = chart_of_accounts.get("Accounts Payable (A/P)")
        payable_account = chart_of_accounts.get("Sales Tax Payable")
        journal_entry_items = journal_entry.journalentryconnector_set
        connector_data = []

        if currency_kind or currency_rate:
            currency, _ = Currency.objects.get_or_create(
                kind=currency_kind,
                exchange_rate=currency_rate,
                company=user.get_active_company(),
            )
            CurrencyConnector.objects.update_or_create(
                credit_note=instance,
                defaults={"currency": currency},
                model_kind=CurrencyConnectorModelKind.CREDIT_NOTE_ITEM,
            )

        if full_address:
            address_connector = AddressConnector.objects.filter(
                credit_note=instance,
                kind=AddressConnectorKindCoices.CREDIT_NOTE_ITEM,
            ).first()
            if address_connector:
                address_connector.address.full_address = full_address
                address_connector.address.save()
            else:
                AddressConnector.objects.create(
                    address=Address.objects.create(
                        full_address=full_address, company=validated_data["company"]
                    ),
                    credit_note=instance,
                    kind=AddressConnectorKindCoices.CREDIT_NOTE_ITEM,
                )

        if tag_titles:
            Tag.objects.filter(
                id__in=TagConnector.objects.filter(credit_note=instance).values_list(
                    "tag_id", flat=True
                )
            ).delete()

            # Add new tags from the update request
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.CREDIT_NOTE_ITEM,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_titles
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        credit_note=instance,
                    )
                    for tag_item in tag_items
                ]
            )

        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.CREDIT_NOTE,
                object=instance,
            )

        if instance.kind == CreditNoteKindChoices.SALE:
            # Both of these SUBTRACT when the note is posted -- a sale credit
            # note lowers what the customer owes, and its A/R leg is a credit.
            # `"update"` reads its direction from whether the figure rose, not
            # from what the posting did, so raising a note from 100 to 150 moved
            # both +50 where they must move -50: an error of twice the delta, on
            # the most frequent edit in this module.
            amend_balance(
                instance.customer,
                JournalEntryConnectorKindChoices.DEBIT,
                validated_data["total"],
                instance.total,
            )

            # Receivable amount
            amend_leg(
                receivable_account,
                JournalEntryConnectorKindChoices.CREDIT,
                validated_data["total"],
                instance.total,
            )

            if journal_entry_items and instance.total != validated_data["total"]:
                # Update receivable account journal entry directly
                receivable_journal_item = journal_entry_items.filter(
                    account=receivable_account
                ).first()

                if receivable_journal_item:
                    new_total = validated_data["total"]
                    receivable_journal_item.credit = new_total
                    receivable_journal_item.total = new_total
                    receivable_journal_item.last_balance = (
                        receivable_account.opening_balance
                    )
                    receivable_journal_item.save_dirty_fields()

            # The tax amend that used to sit here moved the balance of
            # "Sales Tax Payable" -- and the SALE branch of `create` never posts
            # to that account. It posts to `tax_group.sales_tax_account` per
            # item, and to the named accounts in the auto-tax breakdown. So this
            # moved a balance on an account the document has no leg on, and the
            # `.filter(account=payable_account).first()` beneath it always
            # returned None, which is why nothing ever looked wrong.
            #
            # Removed rather than corrected: flipping its sign would only have
            # made it corrupt that account in the other direction. The PURCHASE
            # branch below keeps its tax amend, because there `create` really
            # does post to this account.
            #
            # What is still missing is amending the legs that DO exist. That
            # needs the per-agency split, and the header `total_tax` does not
            # carry it -- a client can change the total without saying which
            # agency it belongs to. Guessing would put the money on the wrong
            # agency, so this reports and leaves the legs alone.
            if instance.total_tax != validated_data.get(
                "total_tax", instance.total_tax
            ):
                logger.warning(
                    "credit note %s: total_tax changed %s -> %s, but a SALE "
                    "credit note's tax legs sit on the agency accounts and the "
                    "payload carries no per-agency split, so they were not "
                    "amended. The entry will not balance until it is re-posted.",
                    instance.pk,
                    instance.total_tax,
                    validated_data.get("total_tax"),
                )

        elif instance.kind == CreditNoteKindChoices.PURCHASE:
            # The mirror of the SALE pair above: a vendor credit lowers what we
            # owe the supplier, and its A/P leg is a debit. Both subtract on
            # posting, and both were amended in the opposite direction.
            amend_balance(
                instance.supplier,
                JournalEntryConnectorKindChoices.DEBIT,
                validated_data["total"],
                instance.total,
            )

            # Account Payable amount
            amend_leg(
                account_payable,
                JournalEntryConnectorKindChoices.DEBIT,
                validated_data["total"],
                instance.total,
            )

            if journal_entry_items and instance.total != validated_data["total"]:
                # Update account payable journal entry directly
                ap_journal_item = journal_entry_items.filter(
                    account=account_payable
                ).first()

                if ap_journal_item:
                    new_total = validated_data["total"]
                    ap_journal_item.debit = new_total
                    ap_journal_item.total = new_total
                    ap_journal_item.last_balance = account_payable.opening_balance
                    ap_journal_item.save_dirty_fields()

            # Sales Tax Payable amount
            if "total_tax" in validated_data:
                # The create leg CREDITS this account -- the bill debited the
                # tax, and a vendor credit reverses it. This amend was written
                # against the old, wrong debit, so it both moved the balance the
                # wrong way and wrote the wrong column.
                amend_leg(
                    payable_account,
                    JournalEntryConnectorKindChoices.CREDIT,
                    validated_data["total_tax"],
                    instance.total_tax,
                )

                if (
                    journal_entry_items
                    and instance.total_tax != validated_data["total_tax"]
                ):
                    # Update sales tax payable journal entry directly
                    payable_journal_item = journal_entry_items.filter(
                        account=payable_account
                    ).first()

                    if payable_journal_item:
                        new_tax_total = validated_data["total_tax"]
                        payable_journal_item.credit = new_tax_total
                        # A row posted before the create leg was corrected still
                        # carries the old debit, and a connector with both
                        # columns populated is counted twice.
                        payable_journal_item.debit = 0
                        payable_journal_item.total = new_tax_total
                        payable_journal_item.last_balance = (
                            payable_account.opening_balance
                        )
                        payable_journal_item.save_dirty_fields()

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=validated_data["total"],
            request_kind=JournalEntryConnectorRequestKindChoices.UPDATED,
            journal_entry=journal_entry,
            customer=instance.customer,
            supplier=instance.supplier,
            created_by=user.get_employee(),
        )
        return super().update(instance, validated_data)


class PrivateCreditNoteItemListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)
    product = PrivateProductSlimSerializer(read_only=True)
    charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    # Fields for creating new items
    product_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Product.objects.all(),
        write_only=True,
        required=False,
    )
    tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=AgencyTax.objects.all(),
        write_only=True,
        required=False,
    )
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = CreditNoteItem
        fields = [
            "uid",
            "section",
            "note",
            "status",
            "description",
            "quantity",
            "item_credit",
            "total",
            "tax",
            "product",
            "charter_account",
            "created_at",
            "updated_at",
            # Write-only fields
            "product_uid",
            "tax_uid",
            "charter_account_uid",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()

        # Get the credit note using the uid from context
        credit_note = get_object_or_404(
            CreditNote.objects.filter(uid=self.context.get("uid"), company=company)
        )

        # Extract fields
        product = validated_data.pop("product_uid", None)
        tax = validated_data.pop("tax_uid", None)
        charter_account = validated_data.pop("charter_account_uid", None)
        quantity = validated_data.get("quantity", 1)

        # Create the credit note item
        credit_note_item = CreditNoteItem.objects.create(
            credit_note=credit_note,
            product=product,
            tax=tax,
            charter_account=charter_account,
            status=CreditNoteItemStatusChoices.ACTIVE,
            **validated_data,
        )

        # Get only necessary chart of accounts
        chart_of_accounts = get_chart_of_account(
            ["Inventory Asset", "Accounts Receivable (A/R)"],
            company,
        )
        inventory_account = chart_of_accounts.get("Inventory Asset")
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        connector_data = []

        journal_entry = JournalEntry.objects.filter(credit_note=credit_note).order_by("id").first()

        # Update balances based on credit note kind
        if credit_note.kind == CreditNoteKindChoices.SALE and product:
            credit_note_date = credit_note.date
            total_income_balance = Decimal(validated_data.pop("total", 0))
            credit_cost = Decimal(0)
            total_cost_of_good = 0

            update_quantity(product, "addition", quantity, 0)

            # Try to get the latest purchase item first
            purchase_item = get_latest_published_purchase_item(
                product=product, company=company, date=credit_note_date
            )

            unit_price = 0
            product_additional_cost = product.productadditionalcost_set.first()

            # Determine unit price: first from purchase item, then from additional cost
            if purchase_item and purchase_item.purchase_price:
                unit_price = purchase_item.purchase_price
            elif product_additional_cost and product_additional_cost.amount:
                unit_price = product_additional_cost.amount

            credit_cost = unit_price * quantity
            total_cost_of_good = credit_cost

            record_credit_note_movement(
                credit_note, credit_note_item, product, quantity,
                inbound=True, unit_price=unit_price,
            )

            # If purchase item exists, update its quantities
            if purchase_item:
                purchase_item.quantity += quantity
                purchase_item.opening_quantity += quantity
                purchase_item.save()

            # Get the cost_of_good_sold_account
            cost_of_good_sold_account = (
                product_additional_cost.expense_account
                if product_additional_cost
                else None
            )
            product_income_account = product.income_account
            product_asset_account = product.asset_account

            append_product_reversal_legs(
                connector_data,
                income_account=product_income_account,
                asset_account=product_asset_account,
                cogs_account=cost_of_good_sold_account,
                total_income=total_income_balance,
                total_cost=total_cost_of_good,
                item=credit_note_item,
                company=credit_note.company,
            )

            # The other half of the line, and it was missing entirely.
            #
            # This path appends legs to the journal entry the note ALREADY has,
            # and it posted only the product side -- revenue, inventory, cost of
            # sales. Adding a line to a posted note therefore debited revenue
            # with nothing credited against it, so the entry went out by the
            # line total in the opposite direction to the create path's fault.
            #
            # A credit note hands value back, so the receivable comes DOWN by
            # what the line is worth. Same leg and same direction the create
            # path writes for the document as a whole; it simply was never
            # written for a line added afterwards.
            if total_income_balance and receivable_account:
                update_opening_balance(
                    receivable_account,
                    JournalEntryConnectorKindChoices.DEBIT,
                    total_income_balance,
                    0,
                )
                connector_data.append(
                    (
                        receivable_account,
                        "substraction",
                        total_income_balance,
                        receivable_account.opening_balance,
                        None,
                        None,
                        None,
                        credit_note_item,
                    )
                )
            elif total_income_balance:
                logger.error(
                    "credit note %s: a line worth %s was added and company %s "
                    "has no Accounts Receivable account, so the receivable "
                    "cannot be reduced. The entry will not balance.",
                    credit_note.pk, total_income_balance, company.pk,
                )
        elif credit_note.kind == CreditNoteKindChoices.PURCHASE and product:
            update_quantity(product, "deduction", quantity, 0)

            total_product_balance = Decimal(credit_note_item.total)

            record_credit_note_movement(
                credit_note, credit_note_item, product, quantity,
                inbound=False,
                unit_price=(
                    total_product_balance / quantity if quantity else None
                ),
            )

            if inventory_account:
                # The item-level twin of the note-create leg: same credit, same
                # inverted balance move.
                inventory_action = action_for_side(
                    inventory_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    inventory_account,
                    balance_operation_for_action(inventory_action),
                    total_product_balance,
                    0,
                )

                if total_product_balance != 0:
                    connector_data.append(
                        (
                            inventory_account,
                            inventory_action,
                            total_product_balance,
                            inventory_account.opening_balance,
                            None,
                            None,
                            None,
                            credit_note_item,
                        )
                    )

        elif (
            credit_note.kind == CreditNoteKindChoices.PURCHASE
            and charter_account
            and not product
        ):
            # Handle charter account for purchase credit notes
            update_opening_balance(
                charter_account,
                JournalEntryConnectorKindChoices.DEBIT,
                credit_note_item.total,
                0,
            )

            if credit_note_item.total != 0:
                connector_data.append(
                    (
                        charter_account,
                        "substraction",
                        credit_note_item.total,
                        charter_account.opening_balance,
                        None,
                        None,
                        None,
                        credit_note_item,
                    )
                )

        # Create journal entry connectors if we have connector data
        if connector_data:
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=credit_note_item.total,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                customer=(
                    credit_note.customer
                    if credit_note.kind == CreditNoteKindChoices.SALE
                    else None
                ),
                supplier=(
                    credit_note.supplier
                    if credit_note.kind == CreditNoteKindChoices.PURCHASE
                    else None
                ),
                created_by=user.get_employee(),
            )

        return credit_note_item


class PrivateCreditNoteItemDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)
    product = PrivateProductSlimSerializer(read_only=True)
    charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    category = PrivateCategorySlimSerializer(
        read_only=True, source="categoryconnector_set.first.category"
    )

    # Fields for updating
    product_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Product.objects.all(),
        write_only=True,
        required=False,
    )
    tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=AgencyTax.objects.all(),
        write_only=True,
        required=False,
    )
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = CreditNoteItem
        fields = [
            "uid",
            "section",
            "note",
            "status",
            "description",
            "quantity",
            "item_credit",
            "total",
            "tax",
            "product",
            "charter_account",
            "category",
            "created_at",
            "updated_at",
            # Write-only fields
            "product_uid",
            "tax_uid",
            "charter_account_uid",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()

        # Get the credit note using the uid from context
        credit_note = get_object_or_404(
            CreditNote.objects.filter(uid=self.context.get("uid"), company=company)
        )

        # Extract fields
        product = validated_data.pop("product_uid", None)
        tax = validated_data.pop("tax_uid", None)
        charter_account = validated_data.pop("charter_account_uid", None)

        # Store old values for comparison
        old_quantity = instance.quantity
        old_total = instance.total
        old_product = instance.product
        old_tax = instance.tax

        # Get new values directly from validated_data
        new_quantity = validated_data.get("quantity", old_quantity)
        new_total = validated_data.get("total", old_total)

        # Update the instance with new data
        if product:
            instance.product = product
        if tax:
            instance.tax = tax
        if charter_account:
            instance.charter_account = charter_account

        # Update fields using super().update() which handles all the field updates
        instance = super().update(instance, validated_data)

        # Get the existing journal entry for this credit note
        journal_entry = JournalEntry.objects.filter(credit_note=credit_note).order_by("id").first()

        # Handle PRODUCT items for SALE credit notes
        if credit_note.kind == CreditNoteKindChoices.SALE and instance.product:

            if new_quantity != old_quantity or old_product != instance.product:
                product = instance.product
                credit_note_date = credit_note.date

                journal_entry_items = journal_entry.journalentryconnector_set.filter(
                    credit_note_item=instance
                )

                # Try to get the latest purchase item first for current product
                purchase_item = get_latest_published_purchase_item(
                    product=product, company=company, date=credit_note_date
                )

                product_additional_cost = product.productadditionalcost_set.first()
                cost_of_good_sold_account = (
                    product_additional_cost.expense_account
                    if product_additional_cost
                    else None
                )
                product_income_account = product.income_account
                product_asset_account = product.asset_account

                # Determine unit price based on purchase item or additional cost
                unit_price = 0
                if purchase_item and purchase_item.purchase_price:
                    unit_price = purchase_item.purchase_price
                elif product_additional_cost and product_additional_cost.amount:
                    unit_price = product_additional_cost.amount

                if new_quantity > old_quantity:
                    # Calculate cost difference using the determined unit price
                    quantity_diff = new_quantity - old_quantity
                    cost_diff = unit_price * quantity_diff
                    income_diff = instance.item_credit * quantity_diff

                    # Update purchase item quantities if it exists
                    if purchase_item:
                        purchase_item.quantity += quantity_diff
                        purchase_item.opening_quantity += quantity_diff
                        purchase_item.save()

                    if cost_of_good_sold_account:
                        # Update cost of goods sold account
                        update_opening_balance(
                            cost_of_good_sold_account,
                            "debit",
                            cost_diff,
                            0,
                        )

                        # Update journal entry for cost of goods sold
                        cost_journal_item = journal_entry_items.filter(
                            account=cost_of_good_sold_account
                        ).first()

                        if cost_journal_item:
                            cost_journal_item.credit = (
                                cost_journal_item.credit + cost_diff
                            )
                            cost_journal_item.total = (
                                cost_journal_item.total + cost_diff
                            )
                            cost_journal_item.last_balance = (
                                cost_of_good_sold_account.opening_balance
                            )
                            cost_journal_item.save_dirty_fields()

                    if product_income_account:
                        update_opening_balance(
                            product_income_account,
                            "debit",
                            income_diff,
                            0,
                        )

                        income_journal_item = journal_entry_items.filter(
                            account=product_income_account
                        ).first()

                        if income_journal_item:
                            income_journal_item.debit = (
                                income_journal_item.debit + income_diff
                            )
                            income_journal_item.total = (
                                income_journal_item.total + income_diff
                            )
                            income_journal_item.last_balance = (
                                product_income_account.opening_balance
                            )
                            income_journal_item.save_dirty_fields()

                    if product_asset_account:
                        # Update product asset account
                        update_opening_balance(
                            product_asset_account,
                            "debit",
                            cost_diff,
                            0,
                        )

                        # Update journal entry for product asset
                        asset_journal_item = journal_entry_items.filter(
                            account=product_asset_account
                        ).first()

                        if asset_journal_item:
                            asset_journal_item.debit = (
                                asset_journal_item.debit + cost_diff
                            )
                            asset_journal_item.total = (
                                asset_journal_item.total + cost_diff
                            )
                            asset_journal_item.last_balance = (
                                product_asset_account.opening_balance
                            )
                            asset_journal_item.save_dirty_fields()

                elif new_quantity < old_quantity:
                    # Handle quantity decrease
                    quantity_diff = old_quantity - new_quantity
                    cost_diff = unit_price * quantity_diff
                    income_diff = instance.item_credit * quantity_diff

                    # Update purchase item quantities if it exists
                    if purchase_item:
                        purchase_item.quantity -= quantity_diff
                        purchase_item.opening_quantity -= quantity_diff
                        purchase_item.save()

                    if cost_of_good_sold_account:
                        # Update cost of goods sold account
                        update_opening_balance(
                            cost_of_good_sold_account,
                            "credit",
                            cost_diff,
                            0,
                        )

                        # Update journal entry for cost of goods sold
                        cost_journal_item = journal_entry_items.filter(
                            account=cost_of_good_sold_account
                        ).first()

                        if cost_journal_item:
                            cost_journal_item.credit = (
                                cost_journal_item.credit - cost_diff
                            )
                            cost_journal_item.total = (
                                cost_journal_item.total - cost_diff
                            )
                            cost_journal_item.last_balance = (
                                cost_of_good_sold_account.opening_balance
                            )
                            cost_journal_item.save_dirty_fields()

                    if product_income_account:
                        # Update product income account
                        update_opening_balance(
                            product_income_account,
                            "credit",
                            income_diff,
                            0,
                        )

                        # Update journal entry for product income account
                        income_journal_item = journal_entry_items.filter(
                            account=product_income_account
                        ).first()

                        if income_journal_item:
                            income_journal_item.debit = (
                                income_journal_item.debit - income_diff
                            )
                            income_journal_item.total = (
                                income_journal_item.total - income_diff
                            )
                            income_journal_item.last_balance = (
                                product_income_account.opening_balance
                            )
                            income_journal_item.save_dirty_fields()

                    if product_asset_account:
                        # Update product asset account
                        update_opening_balance(
                            product_asset_account,
                            "credit",
                            cost_diff,
                            0,
                        )

                        # Update journal entry for product asset
                        asset_journal_item = journal_entry_items.filter(
                            account=product_asset_account
                        ).first()

                        if asset_journal_item:
                            asset_journal_item.debit = (
                                asset_journal_item.debit - cost_diff
                            )
                            asset_journal_item.total = (
                                asset_journal_item.total - cost_diff
                            )
                            asset_journal_item.last_balance = (
                                product_asset_account.opening_balance
                            )
                            asset_journal_item.save_dirty_fields()

                # Handle product change if needed
                if old_product != instance.product and old_product:
                    # Try to get purchase price for old product too
                    old_purchase_item = get_latest_published_purchase_item(
                        product=old_product, company=company, date=credit_note_date
                    )

                    old_unit_price = 0
                    old_product_additional_cost = (
                        old_product.productadditionalcost_set.first()
                    )

                    if old_purchase_item and old_purchase_item.purchase_price:
                        old_unit_price = old_purchase_item.purchase_price
                    elif (
                        old_product_additional_cost
                        and old_product_additional_cost.amount
                    ):
                        old_unit_price = old_product_additional_cost.amount

                    old_cost_amount = old_unit_price * old_quantity

                    # Reverse old product entries
                    if old_product.asset_account:
                        update_opening_balance(
                            old_product.asset_account,
                            "credit",
                            old_cost_amount,
                            0,
                        )

                        # Update journal entry for old product asset
                        old_asset_journal_item = journal_entry_items.filter(
                            account=old_product.asset_account
                        ).first()

                        if old_asset_journal_item:
                            old_asset_journal_item.credit = old_cost_amount
                            old_asset_journal_item.total = old_cost_amount
                            old_asset_journal_item.last_balance = (
                                old_product.asset_account.opening_balance
                            )
                            old_asset_journal_item.save_dirty_fields()

                # Handle total changes for income account
                if new_total != old_total and product_income_account:
                    if new_total > old_total:
                        # Total increase
                        update_opening_balance(
                            product_income_account,
                            "debit",
                            new_total - old_total,
                            0,
                        )

                        # Update journal entry for income account
                        income_journal_item = journal_entry_items.filter(
                            account=product_income_account
                        ).first()

                        if income_journal_item:
                            income_journal_item.debit = new_total
                            income_journal_item.total = new_total
                            income_journal_item.last_balance = (
                                product_income_account.opening_balance
                            )
                            income_journal_item.save_dirty_fields()
                    else:
                        # Total decrease
                        update_opening_balance(
                            product_income_account,
                            "credit",
                            old_total - new_total,
                            0,
                        )

                        # Update journal entry for income account
                        income_journal_item = journal_entry_items.filter(
                            account=product_income_account
                        ).first()

                        if income_journal_item:
                            income_journal_item.debit = new_total
                            income_journal_item.total = new_total
                            income_journal_item.last_balance = (
                                product_income_account.opening_balance
                            )
                            income_journal_item.save_dirty_fields()

                # Update the journal entry amount
                journal_entry.amount = journal_entry.amount + (new_total - old_total)
                journal_entry.save()

        # Handle PRODUCT items for PURCHASE credit notes
        elif credit_note.kind == CreditNoteKindChoices.PURCHASE and instance.product:
            # Check if quantity or product changed
            if new_quantity != old_quantity or old_product != instance.product:
                # Get chart of accounts
                chart_of_accounts = get_chart_of_account(
                    ["Inventory Asset"],
                    company,
                )
                inventory_account = chart_of_accounts.get("Inventory Asset")

                # Update product quantity
                if old_product and old_product != instance.product:
                    update_quantity(old_product, "addition", old_quantity, 0)
                    update_quantity(instance.product, "deduction", new_quantity, 0)
                else:
                    # Update existing product quantity
                    update_quantity(
                        instance.product,
                        "update",
                        new_quantity,
                        old_quantity,
                    )

                # Reverse what the line posted, then post what it now says.
                # Two rows rather than a net delta: the layers the goods left
                # from are not the layers they come back to once anything else
                # has moved in between, and a net movement cannot say which.
                # The ledger is append-only, so this is also the only shape
                # that leaves the amendment legible afterwards.
                record_credit_note_movement(
                    credit_note, instance, old_product or instance.product,
                    old_quantity, inbound=True, reverse=True,
                    note="Reversed by an amendment to this line.",
                )
                record_credit_note_movement(
                    credit_note, instance, instance.product, new_quantity,
                    inbound=False,
                    unit_price=(
                        Decimal(new_total) / new_quantity if new_quantity else None
                    ),
                )

                # Get journal entry items filtered by credit note item
                journal_entry_items = journal_entry.journalentryconnector_set.filter(
                    credit_note_item=instance
                )

                # Handle total changes for inventory account
                if new_total != old_total and inventory_account:
                    # The leg is a CREDIT on inventory sized `new_total`, so a
                    # bigger total is a bigger credit and lowers the asset
                    # further. Both former branches moved the balance the other
                    # way -- they mirrored the create leg as it used to be,
                    # before that leg was corrected to subtract. Left alone they
                    # would have doubled the error on every edit rather than
                    # tracking it. The two branches only ever differed in that
                    # (wrong) direction; the journal write was identical in both,
                    # which is what `amend_leg` collapses.
                    amend_leg(
                        inventory_account,
                        JournalEntryConnectorKindChoices.CREDIT,
                        new_total,
                        old_total,
                    )

                    # Update journal entry for inventory account
                    inventory_journal_item = journal_entry_items.filter(
                        account=inventory_account
                    ).first()

                    if inventory_journal_item:
                        inventory_journal_item.credit = new_total
                        inventory_journal_item.total = new_total
                        inventory_journal_item.last_balance = (
                            inventory_account.opening_balance
                        )
                        inventory_journal_item.save_dirty_fields()

                # Update the journal entry amount
                journal_entry.amount = journal_entry.amount + (new_total - old_total)
                journal_entry.save()

        elif (
            credit_note.kind == CreditNoteKindChoices.PURCHASE
            and instance.charter_account
        ):
            if new_total != old_total or (
                charter_account and instance.charter_account != charter_account
            ):
                # Get journal entry items filtered by credit note item
                journal_entry_items = journal_entry.journalentryconnector_set.filter(
                    credit_note_item=instance
                )

                # Handle total changes
                if new_total != old_total:
                    if new_total > old_total:
                        # Total increased
                        update_opening_balance(
                            instance.charter_account,
                            JournalEntryConnectorKindChoices.DEBIT,
                            new_total - old_total,
                            0,
                        )

                        # Update journal entry for charter account
                        charter_journal_item = journal_entry_items.filter(
                            account=instance.charter_account
                        ).first()

                        if charter_journal_item:
                            charter_journal_item.credit = new_total
                            charter_journal_item.total = new_total
                            charter_journal_item.last_balance = (
                                instance.charter_account.opening_balance
                            )
                            charter_journal_item.save_dirty_fields()
                    else:
                        # Total decreased
                        update_opening_balance(
                            instance.charter_account,
                            JournalEntryConnectorKindChoices.CREDIT,
                            old_total - new_total,
                            0,
                        )

                        # Update journal entry for charter account
                        charter_journal_item = journal_entry_items.filter(
                            account=instance.charter_account
                        ).first()

                        if charter_journal_item:
                            charter_journal_item.credit = new_total
                            charter_journal_item.total = new_total
                            charter_journal_item.last_balance = (
                                instance.charter_account.opening_balance
                            )
                            charter_journal_item.save_dirty_fields()

                # Handle charter account change
                if charter_account and instance.charter_account != charter_account:
                    # Reverse old charter account
                    update_opening_balance(
                        instance.charter_account,
                        JournalEntryConnectorKindChoices.CREDIT,
                        instance.total,
                        0,
                    )

                    # Update journal entry for old charter account
                    old_charter_journal_item = journal_entry_items.filter(
                        account=instance.charter_account
                    ).first()

                    if old_charter_journal_item:
                        old_charter_journal_item.credit = instance.total
                        old_charter_journal_item.total = instance.total
                        old_charter_journal_item.last_balance = (
                            instance.charter_account.opening_balance
                        )
                        old_charter_journal_item.save_dirty_fields()

                    # Add to new charter account
                    update_opening_balance(
                        charter_account,
                        JournalEntryConnectorKindChoices.DEBIT,
                        instance.total,
                        0,
                    )

                    # Update journal entry for new charter account
                    new_charter_journal_item = journal_entry_items.filter(
                        account=charter_account
                    ).first()

                    if new_charter_journal_item:
                        new_charter_journal_item.credit = instance.total
                        new_charter_journal_item.total = instance.total
                        new_charter_journal_item.last_balance = (
                            charter_account.opening_balance
                        )
                        new_charter_journal_item.save_dirty_fields()

                # Update the journal entry amount
                journal_entry.amount = journal_entry.amount + (new_total - old_total)
                journal_entry.save()

        return instance
