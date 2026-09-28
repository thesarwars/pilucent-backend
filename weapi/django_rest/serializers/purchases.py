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

from accounts.choices import ChartOfAccountStatusChoices, ChartOfAccountKindChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from accounts.models import ChartOfAccount

from addressio.models import Address, AddressConnector
from addressio.choices import AddressStatusChoices, AddressConnectorKindCoices
from addressio.django_rest.serializers.common import PrivateAddressSerializer

from agencyio.django_rest.serializers.common import PrivateAgencyTaxSlimSerializer
from agencyio.models import AgencyTax

from common.choices import CurrencyChoices
from common.django_rest.helpers.serializer_scoping import company_scoped
from common.django_rest.helpers.retire_guard import assert_not_retiring_by_patch
from common.django_rest.helpers.balance_helpers import (
    update_opening_balance,
    action_for_side,
    amend_balance,
    amend_leg,
    balance_operation_for_action,
)
from common.django_rest.helpers.quantity_helpers import update_quantity
from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from weapi.django_rest.helpers.bill_terms import resolve_due_date
from weapi.django_rest.helpers.purchase_item_helpers import (
    record_purchase_line_movement,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

# Where a product's cost belongs. Shared with the sale side deliberately: it is
# the same question about the same product, and answering it twice is how the
# two sides come to disagree about one item.
from weapi.django_rest.helpers.sale_posting import resolve_cogs_account
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.file_helpers import (
    get_pdf,
    file_url,
    link_file_to,
)
from common.django_rest.helpers.emails import send_email_to_user

from creditnoteio.choices import CreditNoteStatusChoices
from creditnoteio.django_rest.serializers.common import PrivateCreditNoteSlimSerializer
from creditnoteio.models import CreditNote

from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector

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

from paymentio.choices import PaymentMethodStatusChoices
from paymentio.django_rest.serializers.common import PrivatePaymentMethodSlimSerializer
from paymentio.models import PaymentMethod

from productio.choices import ProductStatusChoices
from productio.django_rest.serializers.common import PrivateProductSlimSerializer
from productio.models import Product

from purchaseio.choices import (
    PurchaseStatus,
    PurchaseItemStatus,
    PurchaseItemkind,
    ExpenseStatusChoices,
    PurchasePaymentItemStatusChoices,
    PurchasePaymentItemModelKindChoices,
)
from purchaseio.django_rest.serializers.common import PrivatePurchaseSlimSerializer
from purchaseio.models import (
    Purchase,
    PurchaseSetting,
    PurchaseItem,
    Expense,
    ExpenseConnector,
    PurchasePayment,
    PurchasePaymentItem,
)
from .payment_methods import PrivateWePaymentMethodDetailsSerializer


from supplierio.django_rest.serializers.common import (
    PrivateSupplierSlimSerializer,
)
from supplierio.models import Supplier

from tagio.choices import TagStatusChoices, TagKindChoices
from tagio.models import Tag, TagConnector

from termio.choicess import TermKindChoices
from termio.django_rest.serializers.common import PrivateTermSlimSerializer
from termio.models import Term, TermConnector

from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer
from wirehouseio.models import Warehouse


import logging

logger = logging.getLogger(__name__)

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

class PrivateWePurchaseListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
    )

    # Currency related
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=True, write_only=True
    )

    # Tag realted
    tag_title_list = JSONField(required=False, write_only=True)

    # Billing address related
    full_billing_address = CharField(write_only=True, required=False)

    # Shipping address related
    full_shipping_address = CharField(write_only=True, required=False)
    shipping_by = CharField(write_only=True, required=False)
    shipping_date = DateField(write_only=True, required=False)
    # Custom expense items related
    custom_expense_items = JSONField(required=False, write_only=True)
    purchase_items = JSONField(required=False, write_only=True)

    # File related
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)

    # Warehouse related
    warehouse_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Warehouse.objects.all(),
        write_only=True,
        required=False,
    )

    # Term related
    term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    purchase_id = CharField(read_only=True)
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(
            status=PaymentMethodStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    payment_method = PrivateWePaymentMethodDetailsSerializer(read_only=True)
    # Checque related
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Purchase
        fields = [
            "uid",
            "purchase_id",
            "tracking_number",
            "date",
            "email",
            "status",
            "discount_kind",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "total",
            "deposit",
            "due_total",
            "description",
            "supplier",
            "supplier_uid",
            # Currency related
            "currency_kind",
            "currency_rate",
            # Purchase item related fields
            # Tag related fields
            "tag_title_list",
            # Billing address related fields
            "full_billing_address",
            "full_shipping_address",
            # Shipping related
            "shipping_by",
            "shipping_date",
            "custom_expense_items",
            "purchase_items",
            # File related fields
            "files",
            "file_description",
            "file_uids",
            # Warehouse related fields
            "warehouse_uid",
            # Bill related fields
            "tax_kind",
            "bill_date",
            "due_date",
            "is_bill",
            "term_uid",
            "payment_method_uid",
            "payment_method",
            # Cheque related
            "charter_account_uid",
            "is_cheque",
            "cheque_number",
            "is_via_expense",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        # Check if at least purchase_items is provided
        if (
            "purchase_items" not in validated_data
            and "custom_expense_items" not in validated_data
        ):
            raise ValidationError({"message": "Select at least one of items."})

        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        # Request user related
        user = self.context["request"].user
        company = user.get_active_company()
        supplier = validated_data.pop("supplier_uid", None)
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        validated_data["supplier"] = supplier
        validated_data["warehouse"] = validated_data.pop("warehouse_uid", None)
        validated_data["tracking_number"] = validated_data.get(
            "tracking_number",
            get_unique_id(Purchase, company.id, "purchase_id", "PURCHASE"),
        )
        validated_data["purchase_id"] = get_unique_id(
            Purchase, company.id, "purchase_id", "PUR"
        )
        validated_data["payment_method"] = validated_data.pop(
            "payment_method_uid", None
        )
        validated_data["charter_account"] = validated_data.pop(
            "charter_account_uid", None
        )
        bank_cash_charter_account = validated_data.get("charter_account")

        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
                "Inventory Asset",
                "Sales Tax Payable",
            ],
            company,
        )

        payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")
        expense_asset_charter_account = chart_of_accounts.get("Inventory Asset")
        tax_charter_account = chart_of_accounts.get("Sales Tax Payable")

        payable_request_open_balance = validated_data.get("due_total", 0)
        tax_request_open_balance = validated_data.get("total_tax", 0)
        total_balance = validated_data.get("total", 0)
        deposit_amount = validated_data.get("deposit", 0)

        term = validated_data.pop("term_uid", None)
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        tag_title_list = validated_data.pop("tag_title_list", None)
        full_billing_address = validated_data.pop("full_billing_address", None)
        full_shipping_address = validated_data.pop("full_shipping_address", None)
        shipping_by = validated_data.pop("shipping_by", None)
        shipping_date = validated_data.pop(
            "shipping_date", datetime.today().strftime("%Y-%m-%d")
        )
        custom_expense_items = validated_data.pop("custom_expense_items", None)
        purchase_items = validated_data.pop("purchase_items", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        connector_data = []

        # A bill with no term of its own inherits the vendor's, and a bill with
        # no due date gets one -- from that term, or due on receipt when there
        # is none. `Purchase.due_date` is plain nullable and nothing read
        # `supplier.termconnector_set` when building a bill, so setting terms on
        # a vendor did nothing and a bill could be raised with no due date at
        # all. Standard §7 and §11.13: absent terms are not an absent date, and
        # the ageing report buckets by due date.
        if validated_data.get("is_bill"):
            resolved_due_date, term = resolve_due_date(
                supplier=validated_data.get("supplier"),
                term=term,
                base_date=(
                    validated_data.get("bill_date") or validated_data.get("date")
                ),
                due_date=validated_data.get("due_date"),
            )
            if resolved_due_date is not None:
                validated_data["due_date"] = resolved_due_date

        # Create purchase
        purchase = Purchase.objects.create(**validated_data)

        # Create term connector. The term may have come from the vendor rather
        # than the request, and the bill records which one it used -- otherwise
        # the vendor could change terms later and this bill's due date would no
        # longer be explicable from anything stored.
        if term:
            TermConnector.objects.create(
                kind=TermKindChoices.PURCHASE,
                purchase=purchase,
                term=term,
            )

        # Create currency connector
        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=user.get_active_company(),
        )
        CurrencyConnector.objects.create(
            currency=currency,
            model_kind=CurrencyConnectorModelKind.PURCHASE,
            purchase=purchase,
        )

        # Create billing address connector
        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address=full_billing_address,
                company=validated_data["company"],
                status=AddressStatusChoices.ACTIVE,
            ),
            purchase=purchase,
            kind=AddressConnectorKindCoices.PURCHASE,
        )

        if shipping_date and shipping_by:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_shipping_address,
                    shipping_by=shipping_by,
                    shipping_date=shipping_date,
                    is_shipping=True,
                    company=validated_data["company"],
                    status=AddressStatusChoices.ACTIVE,
                ),
                purchase=purchase,
                kind=AddressConnectorKindCoices.PURCHASE,
            )

        # Create tag connector
        if tag_title_list:
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.PURCHASE,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        purchase=purchase,
                    )
                    for tag_item in tag_items
                ]
            )

        # Create custom expense items
        if custom_expense_items:
            custom_purchase_items = []
            for custom_expense_item in custom_expense_items:
                charter_account = get_object_or_404(
                    company_scoped(ChartOfAccount.objects.filter(
                        uid=custom_expense_item.get("charter_account_uid", None)
                    ), self)
                )
                item_total = Decimal(custom_expense_item["total"])

                # Directly update the opening balance for each expense item's charter account
                if (
                    validated_data["is_bill"] == True
                    or validated_data["is_cheque"] == True
                ):
                    # A bill / cheque cost line is ALWAYS a debit, and the
                    # account is user-chosen -- it can be any kind. "addition"
                    # only lands on DEBIT for assets and expenses; on a
                    # liability (a tax account, say) it credited, leaving the
                    # entry out of balance by twice the line amount.
                    cost_action = action_for_side(
                        charter_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        charter_account,
                        balance_operation_for_action(cost_action),
                        item_total,
                        0,
                    )

                    # Add to connector data for journal entry immediately
                    connector_data.append(
                        (
                            charter_account,
                            cost_action,
                            item_total,
                            charter_account.opening_balance,
                            None,
                        )
                    )

                custom_purchase_items.append(
                    PurchaseItem(
                        purchase=purchase,
                        section=custom_expense_item["section"],
                        note=custom_expense_item["note"],
                        status=PurchaseItemStatus.PUBLISHED,
                        kind=PurchaseItemkind.EXPENSE,
                        total=item_total,
                        description=custom_expense_item["description"],
                        tax=(
                            get_object_or_404(
                                AgencyTax.objects.filter(
                                    uid=custom_expense_item["tax_uid"],
                                    company=company,
                                )
                            )
                            if custom_expense_item.get("tax_uid")
                            else None
                        ),
                        charter_account=charter_account,
                    )
                )
            # Creating purchase items
            custom_purchase_items = PurchaseItem.objects.bulk_create(
                custom_purchase_items
            )

        if purchase_items:
            created_purchase_items = PurchaseItem.objects.bulk_create(
                [
                    PurchaseItem(
                        purchase=purchase,
                        section=purchase_item["section"],
                        note=purchase_item["note"],
                        status=PurchaseItemStatus.PUBLISHED,
                        kind=PurchaseItemkind.PRODUCT,
                        total=purchase_item["total"],
                        quantity=purchase_item["quantity"],
                        opening_quantity=purchase_item["quantity"],
                        purchase_price=purchase_item["purchase_price"],
                        description=purchase_item["description"],
                        tax=(
                            get_object_or_404(
                                AgencyTax.objects.filter(
                                    uid=purchase_item["tax_uid"], company=company
                                )
                            )
                            if purchase_item.get("tax_uid")
                            else None
                        ),
                        product=get_object_or_404(
                            company_scoped(Product.objects.filter(
                                uid=purchase_item["product_uid"],
                                status=ProductStatusChoices.ACTIVE,
                            ), self)
                        ),
                    )
                    for purchase_item in purchase_items
                ]
            )
            if validated_data["is_bill"] == True or validated_data["is_cheque"] == True:
                for i, purchase_item in enumerate(purchase_items):
                    product = get_object_or_404(
                        company_scoped(Product.objects.filter(
                            uid=purchase_item["product_uid"],
                            status=ProductStatusChoices.ACTIVE,
                        ), self)
                    )
                    if not product.tracks_stock():
                        # A service, project or event line is a cost, not stock.
                        # Running the inventory block for one set a quantity on
                        # it, appended a PURCHASE movement to the ledger and
                        # debited Inventory Asset -- none of which the inventory
                        # reports would ever show, because they filter on
                        # is_inventory. The value existed and could not be
                        # reconciled against anything.
                        #
                        # Not stock, but still a COST, and the bill still credits
                        # A/P for it. `d67d4b7e` skipped the inventory block with
                        # a bare `continue`, which also skipped the debit at the
                        # foot of this loop -- so a service line credited A/P and
                        # debited nothing, and the entry went out by the line
                        # total. Right instinct, wrong reach: the leg to drop was
                        # Inventory Asset, not the cost itself.
                        #
                        # So post the same debit to where this product's cost
                        # actually belongs. `resolve_cogs_account` is the sale
                        # side's answer to the identical question and ends at the
                        # COGS control account, which every company is required
                        # to have -- so there is always somewhere correct, and
                        # dropping the leg is never it.
                        logger.info(
                            "stock: %r is a %s, not stocked -- purchase line "
                            "costed without touching inventory",
                            product.title, product.kind,
                        )
                        cost_account = resolve_cogs_account(product, company)
                        if cost_account is None:
                            # Nothing to post against. Say so loudly rather than
                            # writing half an entry -- the bill is already
                            # crediting A/P for this line.
                            logger.error(
                                "purchase %s: line for %r resolves to no cost "
                                "account, so its debit cannot be posted and the "
                                "entry will be short by %s",
                                purchase.bill_id, product.title,
                                purchase_item["total"],
                            )
                        elif purchase_item["total"] != 0:
                            cost_action = action_for_side(
                                cost_account.kind,
                                JournalEntryConnectorKindChoices.DEBIT,
                            )
                            update_opening_balance(
                                cost_account,
                                balance_operation_for_action(cost_action),
                                purchase_item["total"],
                                0,
                            )
                            connector_data.append(
                                (
                                    cost_account,
                                    cost_action,
                                    purchase_item["total"],
                                    cost_account.opening_balance,
                                    None,
                                    None,
                                    created_purchase_items[i],
                                )
                            )
                        continue

                    update_quantity(
                        product,
                        "addition",
                        purchase_item["quantity"],
                        0,
                    )

                    # Inventory ledger: record the inbound purchase movement
                    # (best-effort — never break the bill/cheque posting).
                    try:
                        import logging as _logging

                        from stockio.choices import StockMovementTypeChoices
                        from stockio.django_rest.services.stock_movement import (
                            record_stock_movement,
                        )

                        record_stock_movement(
                            company=purchase.company,
                            product=product,
                            date=purchase.date or purchase.bill_date,
                            movement_type=StockMovementTypeChoices.PURCHASE,
                            signed_quantity=int(purchase_item["quantity"]),
                            rate=purchase_item["purchase_price"],
                            purchase_item=created_purchase_items[i],
                            created_by=purchase.created_by,
                        )
                    except Exception:
                        _logging.getLogger(__name__).exception(
                            "stock ledger: failed to record PURCHASE movement"
                        )

                    # Stock coming in is ALWAYS a debit to the inventory
                    # account, whatever kind that account is typed as.
                    inventory_action = action_for_side(
                        expense_asset_charter_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )

                    # Add update of opening balance for expense asset
                    update_opening_balance(
                        expense_asset_charter_account,
                        balance_operation_for_action(inventory_action),
                        purchase_item["total"],
                        0,
                    )

                    if purchase_item["total"] != 0:
                        connector_data.append(
                            (
                                expense_asset_charter_account,
                                inventory_action,
                                purchase_item["total"],
                                expense_asset_charter_account.opening_balance,
                                None,
                                None,
                                created_purchase_items[i],
                            )
                        )

        # Create file connector
        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.PURCHASE,
                object=purchase,
            )

        # need to update this part
        if validated_data["is_bill"] == True:
            # Updating supplier opening balance
            update_opening_balance(
                supplier,
                JournalEntryConnectorKindChoices.CREDIT,
                payable_request_open_balance,
                0,
            )

            # A bill's funding leg is ALWAYS a credit.
            payable_action = action_for_side(
                payable_charter_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            # Tax on a purchase is ALWAYS a debit -- the cost lines carry only
            # the net, so the entry balances only if the tax is debited.
            tax_action = action_for_side(
                tax_charter_account.kind,
                JournalEntryConnectorKindChoices.DEBIT,
            )

            # update coa open balance
            update_opening_balance(
                payable_charter_account,
                balance_operation_for_action(payable_action),
                payable_request_open_balance,
                0,
            )

            # Handle opening balance differently based on item types

            update_opening_balance(
                tax_charter_account,
                balance_operation_for_action(tax_action),
                tax_request_open_balance,
                0,
            )

            if payable_request_open_balance != 0:
                connector_data.append(
                    (
                        payable_charter_account,
                        payable_action,
                        payable_request_open_balance,
                        payable_charter_account.opening_balance,
                        None,
                    )
                )

            if tax_request_open_balance != 0:
                connector_data.append(
                    (
                        tax_charter_account,
                        tax_action,
                        tax_request_open_balance,
                        tax_charter_account.opening_balance,
                        None,
                    )
                )

            if deposit_amount != 0:
                # Money leaving to settle part of the bill is ALWAYS a credit,
                # and the funding account is user-chosen -- paying from a credit
                # card (a LIABILITY) made "substraction" resolve to DEBIT.
                deposit_action = action_for_side(
                    bank_cash_charter_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    bank_cash_charter_account,
                    balance_operation_for_action(deposit_action),
                    deposit_amount,
                    0,
                )

                connector_data.append(
                    (
                        bank_cash_charter_account,
                        deposit_action,
                        deposit_amount,
                        bank_cash_charter_account.opening_balance,
                        None,
                    )
                )

        if validated_data["is_cheque"] == True:
            # A cheque ALWAYS credits the account it is drawn on, and that
            # account is user-chosen (it can be a credit card, a LIABILITY).
            cheque_action = action_for_side(
                bank_cash_charter_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            cheque_tax_action = action_for_side(
                tax_charter_account.kind,
                JournalEntryConnectorKindChoices.DEBIT,
            )

            # update coa open balance
            update_opening_balance(
                bank_cash_charter_account,
                balance_operation_for_action(cheque_action),
                total_balance,
                0,
            )

            update_opening_balance(
                tax_charter_account,
                balance_operation_for_action(cheque_tax_action),
                tax_request_open_balance,
                0,
            )

            if total_balance != 0:
                connector_data.append(
                    (
                        bank_cash_charter_account,
                        cheque_action,
                        total_balance,
                        bank_cash_charter_account.opening_balance,
                        None,
                    )
                )

            if tax_request_open_balance != 0:
                connector_data.append(
                    (
                        tax_charter_account,
                        cheque_tax_action,
                        tax_request_open_balance,
                        tax_charter_account.opening_balance,
                        None,
                    )
                )

        if validated_data["is_bill"] == True or validated_data["is_cheque"] == True:
            journal_entry = JournalEntryService.create_journal_entry(
                amount=total_balance,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=(
                    JournalEntryKindChoices.CHEQUE
                    if validated_data["is_cheque"]
                    else JournalEntryKindChoices.PURCHASE
                ),
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=purchase,
            )

            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=total_balance,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                supplier=supplier,
                created_by=user.get_employee(),
            )

        # Email handling
        email = validated_data.get("email", None)
        supplier_email = (
            email.get("customer_email", supplier.email) if email else supplier.email
        )

        emails = []
        if supplier_email:
            emails.append(supplier_email)
        emails += [email.get("cc_emails", "") if email else ""]
        emails += [email.get("bcc_emails", "") if email else ""]

        # Generate PDF and send email if there's a recipient
        if emails:
            # Set title based on purchase type
            if validated_data["is_bill"]:
                title = "BILL"
                label = "bills"
            elif validated_data["is_cheque"]:
                title = "CHEQUE"
                label = "cheques"
            else:
                title = "PURCHASE"
                label = "purchases"

            subject = f"Balanzify {title}"
            request = self.context["request"]

            # Get all purchase items, both product items and custom expense items
            product_purchase_items = purchase.purchaseitem_set.filter(
                kind=PurchaseItemkind.PRODUCT
            )
            custom_expense_items = purchase.purchaseitem_set.filter(
                kind=PurchaseItemkind.EXPENSE
            )

            # Generate PDF
            purchase_pdf = get_pdf(
                self,
                False,
                {
                    "label": label,
                    "template": "emails/purchases/purchase_pdf_template.html",
                    "title": title,
                    "is_report": False,
                    "data": {
                        "company": company,
                        "supplier": supplier,
                        "full_billing_address": full_billing_address,
                        "supplier_email": supplier_email,
                        "purchase": purchase,
                        "purchase_items": product_purchase_items,
                        "custom_expense_items": custom_expense_items,
                        "has_deposit": deposit_amount > 0,
                        "deposit_amount": deposit_amount,
                        "has_due_total": payable_request_open_balance > 0,
                        "due_total": payable_request_open_balance,
                        "description": validated_data.get("description", ""),
                    },
                },
            )

            # Send email
            send_email_to_user(
                {
                    "title": title,
                    "company": company,
                    "supplier": supplier,
                    "url": file_url(purchase_pdf.file, request),
                    "document_type": title,
                },
                "emails/purchases/purchase_email_template.html",
                emails,
                subject,
            )

        return purchase


class PrivateWePurchaseDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    warehouse = PrivateWarehouseSlimSerializer(read_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)

    # Billing address related
    full_billing_address = CharField(write_only=True, required=False)
    billing_address = PrivateAddressSerializer(
        source="get_billing_address",
        read_only=True,
    )

    # Shipping address related
    shipping_address = PrivateAddressSerializer(
        source="get_shipping_address",
        read_only=True,
    )
    full_shipping_address = CharField(write_only=True, required=False)
    shipping_by = CharField(write_only=True, required=False)
    shipping_date = DateField(write_only=True, required=False)

    # Tag related
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
    warehouse_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Warehouse.objects.all(),
        write_only=True,
        required=False,
    )

    # Term related
    terms = PrivateTermSlimSerializer(
        source="termconnector_set.first.term", required=False, read_only=True
    )
    term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(
            status=PaymentMethodStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    payment_method = PrivateWePaymentMethodDetailsSerializer(read_only=True)

    # Checque related
    charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Purchase
        fields = [
            "uid",
            "purchase_id",
            "date",
            "tracking_number",
            "email",
            "status",
            "discount_kind",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "total",
            "deposit",
            "due_total",
            "description",
            "bill_date",
            "due_date",
            "is_bill",
            "tax_kind",
            "warehouse",
            "supplier",
            "terms",
            # Billing address
            "billing_address",
            "full_billing_address",
            # Shipping address
            "shipping_address",
            "full_shipping_address",
            "shipping_by",
            "shipping_date",
            # Charter account
            "charter_account",
            "charter_account_uid",
            # Payment method
            "payment_method",
            "payment_method_uid",
            "is_cheque",
            "cheque_number",
            "tag_title_list",
            "files",
            "file_description",
            "file_uids",
            "warehouse_uid",
            "term_uid",
            "is_via_expense",
            "created_at",
            "updated_at",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        # `status` is writable here and read-only on none of the six
        # detail serializers, so a PATCH could retire the document by
        # writing the column -- skipping every guard, the reversal and
        # the allocation unwind that live in `perform_destroy`.
        assert_not_retiring_by_patch(
            instance, validated_data, document='bill',
        )

        # One guard for both branches. The BILL branch rewrites `debit`,
        # `credit`, `total` and `last_balance` in place on the A/P, tax and
        # deposit legs; the CHEQUE branch rewrites the funding leg, whose
        # account IS the bank the cheque is drawn on. Both mutate legs of an
        # already-posted entry, and the DELETE for this same document has
        # refused a reconciled bill since `bb2a2eb1`.
        assert_not_reconciled(
            JournalEntry.objects.filter(purchase=instance), action="change"
        )

        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["company"] = company
        tag_titles = validated_data.pop("tag_title_list", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        validated_data["charter_account"] = validated_data.pop(
            "charter_account_uid", None
        )
        charter_account = validated_data.get("charter_account")

        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
                "Sales Tax Payable",
            ],
            company,
        )
        payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")
        tax_charter_account = chart_of_accounts.get("Sales Tax Payable")
        journal_entry = JournalEntry.objects.filter(
            purchase=instance,
            kind=(
                JournalEntryKindChoices.CHEQUE
                if instance.is_cheque
                else JournalEntryKindChoices.PURCHASE
            ),
            company=company,
        ).order_by("id").first()
        connector_data = []

        # Updating shipping address
        shipping_by = validated_data.pop("shipping_by", None)
        shipping_date = validated_data.pop(
            "shipping_date", datetime.today().strftime("%Y-%m-%d")
        )
        full_shipping_address = validated_data.pop("full_shipping_address", None)
        shipping_address = instance.get_shipping_address()
        if instance.is_bill == False or full_shipping_address:
            if shipping_address:
                shipping_address.shipping_by = (
                    shipping_by if shipping_by else shipping_address.shipping_by
                )
                shipping_address.shipping_date = (
                    shipping_date if shipping_date else shipping_address.shipping_date
                )
                shipping_address.full_address = (
                    full_shipping_address
                    if full_shipping_address
                    else shipping_address.full_address
                )
                shipping_address.save()
            else:
                AddressConnector.objects.create(
                    address=Address.objects.create(
                        shipping_by=shipping_by,
                        shipping_date=shipping_date,
                        full_address=full_shipping_address,
                        is_shipping=True,
                        company=company,
                        status=AddressStatusChoices.ACTIVE,
                    ),
                    kind=AddressConnectorKindCoices.PURCHASE,
                    purchase=instance,
                    company=company,
                )

        # Updating full billing address
        full_billing_address = validated_data.pop("full_billing_address", None)
        if full_billing_address:
            billing_address = instance.get_billing_address()
            if billing_address:
                billing_address.full_address = full_billing_address
                billing_address.save()
            else:
                AddressConnector.objects.create(
                    address=Address.objects.create(
                        full_address=full_billing_address,
                        is_shipping=False,
                        company=company,
                        status=AddressStatusChoices.ACTIVE,
                    ),
                    kind=AddressConnectorKindCoices.PURCHASE,
                    purchase=instance,
                    company=company,
                )

        # Updating warehouse
        if warehouse := validated_data.pop("warehouse_uid", None):
            validated_data["warehouse"] = warehouse

        # Updating term
        if term := validated_data.pop("term_uid", None):
            TermConnector.objects.update_or_create(
                kind=TermKindChoices.PURCHASE, purchase=instance, term=term
            )

        # Updating tags
        if tag_titles:
            Tag.objects.filter(
                id__in=TagConnector.objects.filter(purchase=instance).values_list(
                    "tag_id", flat=True
                )
            ).delete()

            # Add new tags from the update request
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.PURCHASE,
                        "company": company,
                    },
                )[0]
                for title in tag_titles
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        purchase=instance,
                    )
                    for tag_item in tag_items  # Now correctly iterating through all tags
                ]
            )

        # Updating files
        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=company,
                model_kind=FileItemConnectorModelKindChoices.PURCHASE,
                object=instance,
            )

        # Absent means UNCHANGED, not zero. Every guard below is
        # `if requested != current:`, and all four of these are
        # `DecimalField(default=0.00)` on the model, so DRF makes them
        # `required=False` -- a PATCH that touches only the memo used to read
        # them all as 0, fire every guard, and drive the supplier balance, A/P,
        # Sales Tax Payable and the deposit account to zero. Defaulting to the
        # instance's own value makes an omitted field a no-op, which is what
        # PATCH means. `instance` still holds pre-update values here:
        # `super().update()` has not run yet.
        payable_request_open_balance = validated_data.get(
            "due_total", instance.due_total
        )
        current_due_total = instance.due_total
        tax_request_open_balance = validated_data.get("total_tax", instance.total_tax)
        current_tax_total = instance.total_tax
        total_balance = validated_data.get("total", instance.total)
        current_deposit_amount = instance.deposit
        deposit_amount = validated_data.get("deposit", instance.deposit)
        journal_entry_items = (
            journal_entry.journalentryconnector_set if journal_entry else None
        )

        # Updating supplier opening balance

        # Update the journal entries if this is a bill
        if instance.is_bill:
            # Update supplier opening balance
            if payable_request_open_balance != current_due_total:
                update_opening_balance(
                    instance.supplier,
                    "update",
                    payable_request_open_balance,
                    current_due_total,
                )

            # These three amend on the side the bill posted them on, which the
            # "update" op could not: it moves the stored balance by whether the
            # figure rose or fell and reads no account kind at all, so it stopped
            # mirroring the posting legs the moment those became kind-aware.
            #
            # Two of the three were moving the wrong way on the CONVENTIONAL
            # kinds, not merely on unusual ones. Posting a bill DEBITS Sales Tax
            # Payable -- "Tax on a purchase is ALWAYS a debit", above -- which
            # SUBTRACTS from that liability's stored balance, while raising the
            # tax on an amendment ADDED to it. The deposit leg CREDITS the
            # funding account, subtracting from a bank asset, and again the
            # amendment added. Both left the stored balance disagreeing with a
            # journal that still balanced, which is the one shape the write-time
            # balance check cannot see.
            if payable_request_open_balance != current_due_total:
                amend_leg(
                    payable_charter_account,
                    JournalEntryConnectorKindChoices.CREDIT,
                    payable_request_open_balance,
                    current_due_total,
                )

            if tax_request_open_balance != current_tax_total:
                amend_leg(
                    tax_charter_account,
                    JournalEntryConnectorKindChoices.DEBIT,
                    tax_request_open_balance,
                    current_tax_total,
                )

            if charter_account and current_deposit_amount != deposit_amount:
                amend_leg(
                    charter_account,
                    JournalEntryConnectorKindChoices.CREDIT,
                    deposit_amount,
                    current_deposit_amount,
                )

            # Update journal entries if they exist
            if journal_entry:
                # Update journal entry items directly
                if journal_entry_items:
                    # Update accounts payable entry
                    if payable_request_open_balance != current_due_total:
                        journal_entry_item = journal_entry_items.filter(
                            account=payable_charter_account
                        ).first()
                        if journal_entry_item:
                            journal_entry_item.credit = payable_request_open_balance
                            journal_entry_item.total = payable_request_open_balance
                            journal_entry_item.last_balance = (
                                payable_charter_account.opening_balance
                            )
                            journal_entry_item.save_dirty_fields()

                    # Update tax entry
                    if tax_request_open_balance != current_tax_total:
                        journal_entry_item = journal_entry_items.filter(
                            account=tax_charter_account
                        ).first()
                        if journal_entry_item:
                            journal_entry_item.debit = tax_request_open_balance
                            journal_entry_item.total = tax_request_open_balance
                            journal_entry_item.last_balance = (
                                tax_charter_account.opening_balance
                            )
                            journal_entry_item.save_dirty_fields()

                    # Update charter account entry if it exists
                    # charter_account is already defined at the top of the method
                    if charter_account and current_deposit_amount != deposit_amount:
                        journal_entry_item = journal_entry_items.filter(
                            account=charter_account
                        ).first()
                        if journal_entry_item:
                            journal_entry_item.credit = deposit_amount
                            journal_entry_item.debit = 0
                            journal_entry_item.total = deposit_amount
                            journal_entry_item.last_balance = (
                                charter_account.opening_balance
                            )
                            journal_entry_item.save_dirty_fields()

                # Update payable and expense accounts in connector data
                # if payable_request_open_balance != current_due_total:
                #     connector_data.append(
                #         (
                #             payable_charter_account,
                #             "addition",
                #             payable_request_open_balance,
                #             payable_charter_account.opening_balance,
                #             None,
                #         )
                #     )

                # Update tax account in connector data
                # if tax_request_open_balance != current_tax_total:
                #     connector_data.append(
                #         (
                #             tax_charter_account,
                #             "addition",
                #             tax_request_open_balance,
                #             tax_charter_account.opening_balance,
                #             None,
                #         )
                #     )

                # Update the journal entry amount
                if total_balance != instance.total:
                    journal_entry.amount = total_balance
                    journal_entry.save()

                # Create a new journal entry for the updated values
                # journal_entry = JournalEntry.objects.create(
                #     status=JournalEntryStatusChoices.PUBLISHED,
                #     kind=JournalEntryKindChoices.PURCHASE,
                #     is_transaction=True,
                #     is_journal_entry=False,
                #     company=company,
                #     purchase=instance,
                #     amount=total_balance,
                # )

                # Create journal connectors for the new entry
                # journal_connectors = [
                #     JournalEntryConnector(
                #         debit=0,
                #         credit=payable_request_open_balance,
                #         kind=JournalEntryConnectorKindChoices.CREDIT,
                #         request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                #         journal=journal_entry,
                #         account=payable_charter_account,
                #         last_balance=payable_charter_account.opening_balance,
                #     ),
                # ]

                # if tax_request_open_balance > 0:
                #     journal_connectors.append(
                #         JournalEntryConnector(
                #             debit=tax_request_open_balance,
                #             credit=0,
                #             kind=JournalEntryConnectorKindChoices.DEBIT,
                #             request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                #             journal=journal_entry,
                #             account=tax_charter_account,
                #             last_balance=tax_charter_account.opening_balance,
                #         )
                #     )

                # JournalEntryConnector.objects.bulk_create(journal_connectors)

        # Check if is_cheque is in validated_data or instance before using it
        if (
            validated_data.get("is_cheque", False) or instance.is_cheque
        ) and validated_data.get("charter_account"):

            # Initialize journal_entry_items only if journal_entry exists
            journal_entry_items = (
                journal_entry.journalentryconnector_set if journal_entry else None
            )

            # # update coa open balance for payable account (debit)
            # if total_balance != instance.total:
            #     update_opening_balance(
            #         payable_charter_account,
            #         JournalEntryConnectorKindChoices.DEBIT,
            #         total_balance,
            #         0,
            #     )

            #     # Update journal entry items if they exist
            #     if journal_entry and journal_entry_items:
            #         journal_entry_item = journal_entry_items.filter(
            #             account=payable_charter_account
            #         ).first()
            #         if journal_entry_item:
            #             journal_entry_item.debit = total_balance
            #             journal_entry_item.credit = 0
            #             journal_entry_item.total = total_balance
            #             journal_entry_item.last_balance = (
            #                 payable_charter_account.opening_balance
            #             )
            #             journal_entry_item.save_dirty_fields()

            # update coa open balance for charter account (credit)
            if total_balance != instance.total:
                # Move the stored balance the same way the cheque posted it
                # (see create(), the is_cheque branch), and by the DELTA --
                # this used to add the whole new total on top of the original
                # subtraction.
                amend_account = validated_data["charter_account"]
                amend_action = action_for_side(
                    amend_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    amend_account,
                    balance_operation_for_action(amend_action),
                    total_balance - instance.total,
                    0,
                )

                # Update journal entry items if they exist
                if journal_entry and journal_entry_items:
                    journal_entry_item = journal_entry_items.filter(
                        account=validated_data["charter_account"]
                    ).first()
                    if journal_entry_item:
                        journal_entry_item.credit = total_balance
                        journal_entry_item.debit = 0
                        journal_entry_item.total = total_balance
                        journal_entry_item.last_balance = validated_data[
                            "charter_account"
                        ].opening_balance
                        journal_entry_item.save_dirty_fields()

            if journal_entry:
                # Build connector data for journal entry service
                # if total_balance != instance.total:
                # connector_data.extend(
                #     [
                #         (
                #             payable_charter_account,
                #             "addition",
                #             total_balance,
                #             payable_charter_account.opening_balance,
                #             (
                #                 journal_entry_items.filter(
                #                     account=payable_charter_account
                #                 ).first()
                #                 if journal_entry_items
                #                 else None
                #             ),
                #         ),
                #         (
                #             validated_data["charter_account"],
                #             "substraction",
                #             total_balance,
                #             validated_data["charter_account"].opening_balance,
                #             (
                #                 journal_entry_items.filter(
                #                     account=validated_data["charter_account"]
                #                 ).first()
                #                 if journal_entry_items
                #                 else None
                #             ),
                #         ),
                #     ]
                # )

                # Update the journal entry amount
                journal_entry.amount = total_balance
                journal_entry.save()

                # Create journal entry connector
                JournalEntryService.create_journal_entry_connector(
                    connector_data=connector_data,
                    total=total_balance,
                    request_kind=JournalEntryConnectorRequestKindChoices.UPDATED,
                    journal_entry=journal_entry,
                    supplier=instance.supplier,
                    created_by=user.get_employee(),
                )
        return super().update(instance, validated_data)


def funding_account_for_line_add(purchase, company):
    """The account a newly added purchase line is funded from.

    Adding a line to a document that has already posted needs BOTH legs, not
    just the cost one. A bill increases what is owed, so it credits Accounts
    Payable; a cheque takes the money straight out of the account it is drawn
    on; an expense comes out of the account it was paid from.

    Returns None when the document names no fundable account, which the caller
    reports rather than posting a lone leg.
    """
    if purchase.is_bill:
        return get_chart_of_account(["Accounts Payable (A/P)"], company).get(
            "Accounts Payable (A/P)"
        )
    if purchase.is_cheque:
        return purchase.charter_account
    if purchase.is_via_expense:
        connector = ExpenseConnector.objects.filter(purchase=purchase).first()
        return getattr(getattr(connector, "expense", None), "payment_account", None)
    return None


class PrivateWePurchaseItemListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    # Product related
    product = PrivateProductSlimSerializer(read_only=True)
    product_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Product.objects.filter(status=ProductStatusChoices.ACTIVE),
        write_only=True,
        required=False,
    )

    # Tax Related
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)
    tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=AgencyTax.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    # Account related
    charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PurchaseItem
        fields = [
            "uid",
            "section",
            "note",
            "opening_quantity",
            "kind",
            "total",
            "purchase_price",
            "description",
            "quantity",
            # Product related
            "product",
            "product_uid",
            # Tax related
            "tax",
            "tax_uid",
            # Account related
            "charter_account",
            "charter_account_uid",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    @transaction.atomic
    def create(self, validated_data):
        purchase = get_object_or_404(
            company_scoped(Purchase.objects.filter(uid=self.context.get("uid")), self)
        )
        user = self.context["request"].user
        company = user.get_active_company()

        validated_data["charter_account"] = validated_data.pop(
            "charter_account_uid", None
        )
        validated_data["tax"] = validated_data.pop("tax_uid", None)
        validated_data["product"] = validated_data.pop("product_uid", None)
        validated_data["purchase"] = purchase
        validated_data["status"] = PurchaseItemStatus.PUBLISHED

        # Get quantity and total
        quantity = validated_data.get("quantity", 0)
        total = validated_data.get("total", 0)
        connector_data = []
        charter_account = validated_data.get("charter_account")

        journal_entry = None
        if purchase.is_via_expense:
            expense_connector = ExpenseConnector.objects.filter(
                purchase=purchase
            ).first()
            if expense_connector:
                journal_entry = JournalEntry.objects.filter(
                    expense=expense_connector.expense,
                    kind=JournalEntryKindChoices.EXPENSE,
                    company=company,
                ).order_by("id").first()
        else:
            journal_entry = JournalEntry.objects.filter(
                purchase=purchase,
                kind=(
                    JournalEntryKindChoices.CHEQUE
                    if purchase.is_cheque
                    else JournalEntryKindChoices.PURCHASE
                ),
                company=company,
            ).order_by("id").first()

        purchase_item = super().create(validated_data)

        # Resolved BEFORE any balance moves. Adding a line needs both legs, so a
        # document with nothing to fund it from must post neither -- moving a
        # balance with no journal line beside it is the same divergence this
        # sweep has been closing everywhere else.
        funding_account = funding_account_for_line_add(purchase, company)
        posts_to_ledger = journal_entry is not None and funding_account is not None
        if journal_entry is not None and funding_account is None:
            logger.error(
                "purchase %s: added a line for %s but the document names no "
                "account to fund it from, so no legs were posted.",
                purchase.pk, total,
            )

        if (
            (purchase.is_bill or purchase.is_cheque or purchase.is_via_expense)
            and validated_data["product"]
            and validated_data.get("kind") == PurchaseItemkind.PRODUCT
            and posts_to_ledger
        ):
            # Only stocked items move stock -- the mirror of the guard
            # `d67d4b7e` added to create(), which never reached this path. A
            # service, project or event product had a quantity set on it and
            # its cost capitalised into Inventory Asset, where the inventory
            # reports cannot show it because they filter on `is_inventory`.
            #
            # The cost is still a cost, so it is redirected rather than
            # dropped. `4ab99db3` is what dropping it costs.
            line_product = validated_data["product"]
            if line_product.tracks_stock():
                update_quantity(
                    line_product,
                    "addition",
                    quantity,
                    0,
                )

                # The line is the cost layer, exactly as it is on bill create.
                record_purchase_line_movement(
                    purchase, instance, line_product, quantity,
                    unit_cost=validated_data.get("purchase_price"),
                )

            # Get inventory asset account
            chart_of_accounts = get_chart_of_account(
                ["Inventory Asset"],
                company,
            )
            expense_asset_charter_account = (
                chart_of_accounts.get("Inventory Asset")
                if line_product.tracks_stock()
                else resolve_cogs_account(line_product, company)
            )

            if expense_asset_charter_account:
                inventory_action = action_for_side(
                    expense_asset_charter_account.kind,
                    JournalEntryConnectorKindChoices.DEBIT,
                )
                update_opening_balance(
                    expense_asset_charter_account,
                    balance_operation_for_action(inventory_action),
                    total,
                    0,
                )

                connector_data.append(
                    (
                        expense_asset_charter_account,
                        inventory_action,
                        total,
                        expense_asset_charter_account.opening_balance,
                        None,
                        None,
                        purchase_item,
                    )
                )

                # Both legs, or neither. This used to append only the cost leg to
                # the already-posted entry, so adding a line to a bill debited
                # inventory or expense and credited nothing -- the entry left
                # balanced became unbalanced by exactly the line. Producing
                # unbalanced entries from a live endpoint is also what stops the
                # write-time balance check being turned into a raise.
                funding_action = action_for_side(
                    funding_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    funding_account,
                    balance_operation_for_action(funding_action),
                    total,
                    0,
                )
                connector_data.append(
                    (
                        funding_account,
                        funding_action,
                        total,
                        funding_account.opening_balance,
                        None,
                    )
                )

                if connector_data:
                    JournalEntryService.create_journal_entry_connector(
                        connector_data=connector_data,
                        total=total,
                        request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                        journal_entry=journal_entry,
                        supplier=purchase.supplier,
                        created_by=user.get_employee(),
                    )

        elif (
            (purchase.is_bill or purchase.is_cheque or purchase.is_via_expense)
            and validated_data.get("kind") == PurchaseItemkind.EXPENSE
            and charter_account
            and posts_to_ledger
        ):
            # An expense line on a bill / cheque is ALWAYS a debit, and the
            # account is user-chosen -- "addition" credits it on liabilities,
            # equities and incomes.
            cost_action = action_for_side(
                charter_account.kind,
                JournalEntryConnectorKindChoices.DEBIT,
            )
            update_opening_balance(
                charter_account,
                balance_operation_for_action(cost_action),
                total,
                0,
            )

            connector_data.append(
                (
                    charter_account,
                    cost_action,
                    total,
                    charter_account.opening_balance,
                    None,
                )
            )

            # Both legs, or neither. This used to append only the cost leg to
            # the already-posted entry, so adding a line to a bill debited
            # inventory or expense and credited nothing -- the entry left
            # balanced became unbalanced by exactly the line. Producing
            # unbalanced entries from a live endpoint is also what stops the
            # write-time balance check being turned into a raise.
            funding_action = action_for_side(
                funding_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            update_opening_balance(
                funding_account,
                balance_operation_for_action(funding_action),
                total,
                0,
            )
            connector_data.append(
                (
                    funding_account,
                    funding_action,
                    total,
                    funding_account.opening_balance,
                    None,
                )
            )

            if connector_data:
                JournalEntryService.create_journal_entry_connector(
                    connector_data=connector_data,
                    total=total,
                    request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                    journal_entry=journal_entry,
                    supplier=purchase.supplier,
                    created_by=user.get_employee(),
                )

        return purchase_item


class PrivateWePurchaseItemDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    product = PrivateProductSlimSerializer(read_only=True)
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)
    product_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Product.objects.filter(status=ProductStatusChoices.ACTIVE),
        write_only=True,
    )
    tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=AgencyTax.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,  # Add allow_null parameter to handle null values
    )
    charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PurchaseItem
        fields = [
            "uid",
            "section",
            "note",
            "opening_quantity",
            "status",
            "kind",
            "total",
            "purchase_price",
            "description",
            "quantity",
            "product",
            "product_uid",
            "tax",
            "tax_uid",
            "charter_account",
            "charter_account_uid",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "uid",
            "status",
            "kind",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        product_uid = validated_data.get("product_uid", None)
        if self.instance.kind != PurchaseItemkind.PRODUCT and product_uid:
            raise ValidationError({"message": "You can't update product."})
        validated_data["product"] = product_uid
        return super().validate(validated_data)

    @set_auditlog_actor
    @transaction.atomic
    def update(self, instance, validated_data):
        if "tax_uid" in validated_data:
            tax_uid = validated_data.pop("tax_uid")
            if tax_uid == "":
                tax_uid = None
            validated_data["tax"] = (
                None
                if tax_uid is None
                else get_object_or_404(
                    AgencyTax.objects.filter(
                        uid=tax_uid,
                        company=self.context["request"].user.get_active_company(),
                    )
                )
            )
        if charter_account := validated_data.get("charter_account_uid", None):
            validated_data["charter_account"] = charter_account

        purchase = instance.purchase
        user = self.context["request"].user
        company = user.get_active_company()

        # Handle PRODUCT items for is_bill or is_cheque
        if (
            (purchase.is_bill or purchase.is_cheque or purchase.is_via_expense)
            and instance.kind == PurchaseItemkind.PRODUCT
            and instance.product
        ):
            new_quantity = validated_data.get(
                "opening_quantity", instance.opening_quantity
            )
            old_quantity = instance.opening_quantity

            # Guard only, no redirect: this adjusts stock for a quantity
            # change and posts no ledger leg, so there is nothing to reroute.
            # A non-stocked item simply has no stock to adjust.
            if new_quantity != old_quantity and instance.product.tracks_stock():
                update_quantity(
                    instance.product,
                    "update",
                    new_quantity,
                    old_quantity,
                )

                # Reverse what the line put in, then put in what it now says.
                # Two rows rather than a delta, for the reason the credit-note
                # amend gives: on an append-only ledger a net movement cannot
                # say WHICH layer moved, and once anything else has been sold
                # in between that is the only question that matters.
                record_purchase_line_movement(
                    purchase, instance, instance.product, old_quantity,
                    inbound=False, unit_cost=instance.purchase_price,
                    note="Reversed by an amendment to this line.",
                )
                record_purchase_line_movement(
                    purchase, instance, instance.product, new_quantity,
                    unit_cost=instance.purchase_price,
                )

                journal_entry = None
                if purchase.is_via_expense:
                    expense_connector = ExpenseConnector.objects.filter(
                        purchase=purchase
                    ).first()
                    if expense_connector:
                        journal_entry = JournalEntry.objects.filter(
                            expense=expense_connector.expense,
                            kind=JournalEntryKindChoices.EXPENSE,
                            company=company,
                        ).order_by("id").first()
                else:
                    journal_entry = JournalEntry.objects.filter(
                        purchase=purchase,
                        kind=(
                            JournalEntryKindChoices.CHEQUE
                            if purchase.is_cheque
                            else JournalEntryKindChoices.PURCHASE
                        ),
                        company=company,
                    ).order_by("id").first()

                if journal_entry:
                    chart_of_accounts = get_chart_of_account(
                        ["Inventory Asset"],
                        company,
                    )
                    inventory_asset_account = chart_of_accounts.get("Inventory Asset")

                    old_total = instance.total
                    new_total = validated_data.get("total", old_total)

                    if inventory_asset_account:
                        # Get journal entry items filtered by purchase_item
                        journal_entry_items = (
                            journal_entry.journalentryconnector_set.filter(
                                purchase_item=instance
                            )
                        )

                        if new_quantity > old_quantity:

                            # Update opening balance for inventory asset account
                            update_opening_balance(
                                inventory_asset_account,
                                JournalEntryConnectorKindChoices.CREDIT,
                                new_total - old_total,
                                0,
                            )

                            # validated_data["opening_quantity"] = (
                            #     instance.opening_quantity
                            #     + (new_quantity - old_quantity)
                            # )

                            if journal_entry_items.exists():
                                inventory_journal_item = journal_entry_items.filter(
                                    account=inventory_asset_account
                                ).first()
                                if inventory_journal_item:
                                    inventory_journal_item.debit = new_total
                                    inventory_journal_item.total = new_total
                                    inventory_journal_item.last_balance = (
                                        inventory_asset_account.opening_balance
                                    )
                                    # Save the updated journal entry item
                                    inventory_journal_item.save_dirty_fields()

                        elif new_quantity < old_quantity:

                            # Update opening balance for inventory asset account with subtraction
                            update_opening_balance(
                                inventory_asset_account,
                                JournalEntryConnectorKindChoices.DEBIT,
                                old_total - new_total,
                                0,
                            )

                            # validated_data["opening_quantity"] = (
                            #     instance.opening_quantity
                            #     + (new_quantity - old_quantity)
                            # )

                            if journal_entry_items.exists():
                                inventory_journal_item = journal_entry_items.filter(
                                    account=inventory_asset_account
                                ).first()
                                if inventory_journal_item:
                                    inventory_journal_item.debit = new_total
                                    inventory_journal_item.total = new_total
                                    inventory_journal_item.last_balance = (
                                        inventory_asset_account.opening_balance
                                    )
                                    # Save the updated journal entry item
                                    inventory_journal_item.save_dirty_fields()

                    # Update the journal entry amount to reflect the new total
                    old_journal_amount = journal_entry.amount
                    if new_quantity > old_quantity:
                        journal_entry.amount = old_journal_amount + (
                            new_total - old_total
                        )
                    else:
                        journal_entry.amount = old_journal_amount - (
                            old_total - new_total
                        )
                    journal_entry.save()

        # Handle EXPENSE items for is_bill or is_cheque
        elif (
            (purchase.is_bill or purchase.is_cheque or purchase.is_via_expense)
            and instance.kind == PurchaseItemkind.EXPENSE
            and instance.charter_account
        ):
            old_total = instance.total
            new_total = validated_data.get("total", old_total)
            charter_account = validated_data.get(
                "charter_account", instance.charter_account
            )

            if new_total != old_total:

                journal_entry = None
                if purchase.is_via_expense:
                    expense_connector = ExpenseConnector.objects.filter(
                        purchase=purchase
                    ).first()
                    if expense_connector:
                        journal_entry = JournalEntry.objects.filter(
                            expense=expense_connector.expense,
                            kind=JournalEntryKindChoices.EXPENSE,
                            company=company,
                        ).order_by("id").first()
                else:
                    journal_entry = JournalEntry.objects.filter(
                        purchase=purchase,
                        kind=(
                            JournalEntryKindChoices.CHEQUE
                            if purchase.is_cheque
                            else JournalEntryKindChoices.PURCHASE
                        ),
                        company=company,
                    ).order_by("id").first()

                if journal_entry:
                    # EXPENSE branch only. The PRODUCT branch above touches
                    # Inventory Asset, which no `BankReconciliation` can cover --
                    # a session is keyed to a bank account. Here the account is
                    # the user's own `charter_account`, picked from `selectable()`
                    # with no money filter, so a bank account is a legal target.
                    assert_not_reconciled([journal_entry], action="change")

                    journal_entry_items = (
                        journal_entry.journalentryconnector_set.filter(
                            account=charter_account
                        )
                    )

                    # The line was posted as a DEBIT (see create()); the amend
                    # has to restate that same side, not write a credit onto
                    # the row beside the untouched original debit.
                    cost_action = action_for_side(
                        charter_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    posting_op = balance_operation_for_action(cost_action)
                    undo_op = (
                        JournalEntryConnectorKindChoices.DEBIT
                        if posting_op == JournalEntryConnectorKindChoices.CREDIT
                        else JournalEntryConnectorKindChoices.CREDIT
                    )

                    if new_total > old_total:
                        update_opening_balance(
                            charter_account,
                            posting_op,
                            new_total - old_total,
                            0,
                        )

                        if journal_entry_items.exists():
                            charter_journal_item = journal_entry_items.first()
                            if charter_journal_item:
                                charter_journal_item.kind = (
                                    JournalEntryConnectorKindChoices.DEBIT
                                )
                                charter_journal_item.debit = new_total
                                charter_journal_item.credit = 0
                                charter_journal_item.total = new_total
                                charter_journal_item.last_balance = (
                                    charter_account.opening_balance
                                )
                                charter_journal_item.save_dirty_fields()

                    elif new_total < old_total:
                        update_opening_balance(
                            charter_account,
                            undo_op,
                            old_total - new_total,
                            0,
                        )

                        # Update journal entries if they exist
                        if journal_entry_items.exists():
                            charter_journal_item = journal_entry_items.first()
                            if charter_journal_item:
                                charter_journal_item.kind = (
                                    JournalEntryConnectorKindChoices.DEBIT
                                )
                                charter_journal_item.debit = new_total
                                charter_journal_item.credit = 0
                                charter_journal_item.total = new_total
                                charter_journal_item.last_balance = (
                                    charter_account.opening_balance
                                )
                                # Save the updated journal entry item
                                charter_journal_item.save_dirty_fields()

                    # Update the journal entry amount to reflect the new total
                    old_journal_amount = journal_entry.amount
                    if new_total > old_total:
                        journal_entry.amount = old_journal_amount + (
                            new_total - old_total
                        )
                    else:
                        journal_entry.amount = old_journal_amount - (
                            old_total - new_total
                        )
                    journal_entry.save()

        return super().update(instance, validated_data)


class PrivateWeExpenseListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
    )
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.filter(status=PaymentMethodStatusChoices.ACTIVE),
        write_only=True,
    )
    payment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
    )
    purchase_uids = JSONField(required=False, write_only=True)

    class Meta:
        model = Expense
        fields = [
            "uid",
            "date",
            "reference_number",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "total",
            "deposit",
            "due_total",
            "description",
            "supplier_uid",
            "supplier",
            "payment_method_uid",
            "payment_account_uid",
            "purchase_uids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "supplier",
            "payment_method",
            "payment_account",
            "created_at",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()

        supplier = validated_data.pop("supplier_uid", None)
        validated_data["supplier"] = supplier
        validated_data["created_by"] = user.get_employee()
        validated_data["status"] = ExpenseStatusChoices.PUBLISHED
        validated_data["payment_method"] = validated_data.pop(
            "payment_method_uid", None
        )
        validated_data["payment_account"] = validated_data.pop(
            "payment_account_uid", None
        )
        total = validated_data.get("total", 0)
        validated_data["total"] = total
        payment_account = validated_data.get("payment_account")
        purchase_uids = validated_data.pop("purchase_uids", None)
        expense = Expense.objects.create(**validated_data)
        purchases = Purchase.objects.filter(
            uid__in=purchase_uids,
            status__in=[
                PurchaseStatus.ACCEPTED,
                PurchaseStatus.PENDING,
                PurchaseStatus.OPEN,
            ],
        )

        ExpenseConnector.objects.bulk_create(
            [
                ExpenseConnector(
                    expense=expense,
                    purchase=purchase,
                )
                for purchase in purchases
            ]
        )

        # Get the necessary chart of accounts
        chart_of_accounts = get_chart_of_account(
            [
                "Sales Tax Payable",
                "Inventory Asset",
            ],
            company,
        )

        tax_charter_account = chart_of_accounts.get("Sales Tax Payable")
        inventory_charter_account = chart_of_accounts.get("Inventory Asset")
        connector_data = []
        # Process each purchase separately

        for purchase in purchases:
            product_items = PurchaseItem.objects.filter(
                purchase=purchase, kind=PurchaseItemkind.PRODUCT
            )
            requested_open_balance = purchase.due_total
            tax_request_open_balance = purchase.total_tax
            total_open_balance = purchase.total

            if product_items.exists():
                # Split by whether the item actually holds stock -- the mirror
                # of the guard `d67d4b7e` added to create() and never brought
                # here. A service, project or event product had a quantity set
                # on it and its cost capitalised into Inventory Asset, which no
                # inventory report can show because they filter on
                # `is_inventory`.
                #
                # The cost is redirected, not dropped: total debits across the
                # entry are unchanged by this split.
                stocked, unstocked = [], []
                for product_item in product_items:
                    if not product_item.product:
                        continue
                    if product_item.product.tracks_stock():
                        stocked.append(product_item)
                    else:
                        unstocked.append(product_item)

                # Inventory coming in is ALWAYS a debit, whatever kind the
                # inventory account is typed as.
                inventory_action = action_for_side(
                    inventory_charter_account.kind,
                    JournalEntryConnectorKindChoices.DEBIT,
                )

                # Sum of the STOCKED lines, not the document net of tax. The
                # bulk figure moved the stored balance by the whole document
                # while the connectors below move it per line, so the two
                # disagreed by whatever was not a stocked product line -- the
                # same drift `19139eeb` corrected in the expense importer, and
                # one no debits-vs-credits check can see because the journal
                # itself stays right.
                stocked_total = sum(
                    (product_item.total for product_item in stocked), Decimal("0")
                )
                if stocked_total:
                    update_opening_balance(
                        inventory_charter_account,
                        balance_operation_for_action(inventory_action),
                        stocked_total,
                        0,
                    )

                # Update quantity for each stocked item individually
                for product_item in stocked:
                    update_quantity(
                        product_item.product, "addition", product_item.quantity, 0
                    )

                    # Stock bought through an expense is stock. It became a
                    # ledger layer on the bill route and not on this one, so
                    # goods entering here sold at whatever cost some other
                    # layer happened to carry.
                    record_purchase_line_movement(
                        purchase, product_item, product_item.product,
                        product_item.quantity,
                        unit_cost=product_item.purchase_price,
                    )
                    connector_data.append(
                        (
                            inventory_charter_account,
                            inventory_action,
                            product_item.total,
                            inventory_charter_account.opening_balance,
                            None,
                            None,
                            product_item,
                        )
                    )

                # Non-stocked items: same debit, to where their cost belongs.
                for product_item in unstocked:
                    cost_account = resolve_cogs_account(
                        product_item.product, company
                    )
                    if cost_account is None or not product_item.total:
                        if product_item.total:
                            logger.error(
                                "purchase %s: %s of cost for %r has no cost "
                                "account, so its debit cannot be posted",
                                purchase.pk, product_item.total,
                                product_item.product.title,
                            )
                        continue
                    cost_action = action_for_side(
                        cost_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        cost_account,
                        balance_operation_for_action(cost_action),
                        product_item.total,
                        0,
                    )
                    connector_data.append(
                        (
                            cost_account,
                            cost_action,
                            product_item.total,
                            cost_account.opening_balance,
                            None,
                            None,
                            product_item,
                        )
                    )

            # Process expense items
            expense_items = PurchaseItem.objects.filter(
                purchase=purchase, kind=PurchaseItemkind.EXPENSE
            )

            if expense_items.exists():
                for expense_item in expense_items:

                    if expense_item.charter_account:
                        # An expense line is ALWAYS a debit and its account is
                        # user-chosen -- "addition" credited it whenever the
                        # line was coded to a liability, equity or income
                        # account.
                        cost_action = action_for_side(
                            expense_item.charter_account.kind,
                            JournalEntryConnectorKindChoices.DEBIT,
                        )
                        # Update opening balances for expense items
                        update_opening_balance(
                            expense_item.charter_account,
                            balance_operation_for_action(cost_action),
                            expense_item.total,
                            0,
                        )

                        connector_data.append(
                            (
                                expense_item.charter_account,
                                cost_action,
                                expense_item.total,
                                expense_item.charter_account.opening_balance,
                                None,
                            )
                        )

            if total_open_balance != 0:
                # Paying for the purchase ALWAYS credits the funding account,
                # which is user-chosen and may be a credit card (LIABILITY),
                # where "substraction" resolves to DEBIT.
                payment_action = action_for_side(
                    payment_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    payment_account,
                    balance_operation_for_action(payment_action),
                    total_open_balance,
                    0,
                )
                connector_data.append(
                    (
                        payment_account,
                        payment_action,
                        total_open_balance,
                        payment_account.opening_balance,
                        None,
                    )
                )
            if tax_request_open_balance != 0:
                # Tax on a purchase is ALWAYS a debit -- the cost legs carry
                # only the net, so the entry balances only if tax is debited.
                tax_action = action_for_side(
                    tax_charter_account.kind,
                    JournalEntryConnectorKindChoices.DEBIT,
                )
                update_opening_balance(
                    tax_charter_account,
                    balance_operation_for_action(tax_action),
                    tax_request_open_balance,
                    0,
                )
                connector_data.append(
                    (
                        tax_charter_account,
                        tax_action,
                        tax_request_open_balance,
                        tax_charter_account.opening_balance,
                        None,
                    )
                )

        journal_entry = JournalEntryService.create_journal_entry(
            amount=total,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.EXPENSE,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=expense,
        )

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            supplier=supplier,
            created_by=user.get_employee(),
        )
        purchases.update(
            status=PurchaseStatus.COMPLETED, due_total=0, is_via_expense=True
        )
        return expense


class PrivateWeExpenseDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    payment_method = PrivatePaymentMethodSlimSerializer(read_only=True)
    payment_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    # Add write fields for update
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.filter(status=PaymentMethodStatusChoices.ACTIVE),
        write_only=True,
        required=False,
    )
    payment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().filter(
            status=ChartOfAccountStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Expense
        fields = [
            "uid",
            "date",
            "reference_number",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "total",
            "deposit",
            "due_total",
            "description",
            "supplier",
            "created_by",
            "payment_method",
            "payment_account",
            "supplier_uid",
            "payment_method_uid",
            "payment_account_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "supplier",
            "created_by",
            "payment_method",
            "payment_account",
            "created_at",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["payment_method"] = validated_data.pop(
            "payment_method_uid", None
        )
        validated_data["payment_account"] = validated_data.pop(
            "payment_account_uid", None
        )
        validated_data["supplier"] = validated_data.pop("supplier_uid", None)

        current_total = instance.total
        new_total = validated_data.get("total", current_total)

        if new_total != current_total:
            payment_account = validated_data.get(
                "payment_account", instance.payment_account
            )
            if payment_account:
                # Inside the branch, not at the top of `update`: the funding leg
                # is only rewritten when the total actually changes, so guarding
                # the whole method would refuse a description-only edit that
                # touches no ledger row at all.
                assert_not_reconciled(
                    JournalEntry.objects.filter(
                        expense=instance,
                        kind=JournalEntryKindChoices.EXPENSE,
                        company=company,
                    ),
                    action="change",
                )

                # Money leaving CREDITS the funding account, which the connector
                # below already records; the balance move has to follow the same
                # side or the two drift apart on every edit.
                amend_leg(
                    payment_account,
                    JournalEntryConnectorKindChoices.CREDIT,
                    new_total,
                    current_total,
                )

                journal_entry = JournalEntry.objects.filter(
                    expense=instance,
                    kind=JournalEntryKindChoices.EXPENSE,
                    company=company,
                ).order_by("id").first()

                if journal_entry:
                    journal_entry.amount = new_total
                    journal_entry.save()

                    journal_entry_connector = (
                        journal_entry.journalentryconnector_set.filter(
                            account=payment_account
                        ).first()
                    )

                    if journal_entry_connector:
                        journal_entry_connector.credit = new_total
                        journal_entry_connector.total = new_total
                        journal_entry_connector.last_balance = (
                            payment_account.opening_balance
                        )
                        journal_entry_connector.save_dirty_fields()

        return super().update(instance, validated_data)


class PrivateWePurchasePaymentListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
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
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(
            status=PaymentMethodStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    payment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    full_billing_address = CharField(write_only=True, required=False)
    purchase_payment_items = JSONField(required=False, write_only=True)
    credit_note_payment_items = JSONField(required=False, write_only=True)
    tag_title_list = JSONField(required=False, write_only=True)
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    payment_method = PrivatePaymentMethodSlimSerializer(read_only=True)
    payment_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    class Meta:
        model = PurchasePayment
        fields = [
            "uid",
            "date",
            "email",
            "status",
            "bill_number",
            "total",
            "deposit",
            "due_total",
            "description",
            "payment_method_uid",
            "supplier_uid",
            "payment_account_uid",
            "full_billing_address",
            "purchase_payment_items",
            "credit_note_payment_items",
            "tag_title_list",
            "files",
            "file_description",
            "file_uids",
            "supplier",
            "payment_method",
            "payment_account",
            "created_at",
            "updated_at",
            # Crurrency related
            "currency_kind",
            "currency_rate",
        ]

    read_only_fields = ["uid", "created_by", "created_at", "updated_at"]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        supplier = validated_data.pop("supplier_uid", None)
        validated_data["supplier"] = supplier
        validated_data["payment_method"] = validated_data.pop(
            "payment_method_uid", None
        )
        validated_data["payment_account"] = validated_data.pop(
            "payment_account_uid", None
        )
        payment_account = validated_data.get("payment_account")
        payable_request_total_balance = validated_data.get("total", 0)
        validated_data["total"] = payable_request_total_balance
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        full_billing_address = validated_data.pop("full_billing_address", None)
        purchase_payment_items = validated_data.pop("purchase_payment_items", None)
        credit_note_payment_items = validated_data.pop(
            "credit_note_payment_items", None
        )
        tag_title_list = validated_data.pop("tag_title_list", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
                # "Inventory Asset",
            ],
            company,
        )
        payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")
        # inventory_account = chart_of_accounts.get("Inventory Asset")
        # inventory_account = chart_of_accounts.get("Inventory Asset")

        connector_data = []

        purchase_payment = super().create(validated_data)

        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=user.get_active_company(),
        )
        CurrencyConnector.objects.create(
            currency=currency,
            purchase_payment=purchase_payment,
            model_kind=CurrencyConnectorModelKind.PURCHASE_PAYMENT,
        )

        if full_billing_address:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_billing_address,
                    company=validated_data["company"],
                ),
                kind=AddressConnectorKindCoices.PURCHASE_PAYMENT,
                purchase_payment=purchase_payment,
            )

        if purchase_payment_items:
            for purchase_payment_item in purchase_payment_items:
                purchase = get_object_or_404(
                    company_scoped(Purchase.objects.filter(
                        uid=purchase_payment_item.get("purchase_uid")
                    ), self)
                )
                item = PurchasePaymentItem.objects.create(
                    purchase_payment=purchase_payment,
                    status=PurchasePaymentItemStatusChoices.DRAFT,
                    model_kind=PurchasePaymentItemModelKindChoices.PURCHASE,
                    total=purchase_payment_item.get("total"),
                    used_total=purchase_payment_item.get("used_total"),
                    purchase=purchase,
                )
                item.save()

                # Apply payment to the purchase
                purchase.apply_purchase_payment(purchase_payment_item.get("used_total"))

                # If due_total becomes 0, set status to COMPLETED
                if purchase.due_total == 0:
                    purchase.status = PurchaseStatus.COMPLETED

                purchase.save()

            # Update the payable charter account opening balance
            update_opening_balance(
                supplier,
                JournalEntryConnectorKindChoices.DEBIT,
                payable_request_total_balance,
                0,
            )

            # Paying a bill ALWAYS debits the payable.
            payable_action = action_for_side(
                payable_charter_account.kind,
                JournalEntryConnectorKindChoices.DEBIT,
            )

            # update coa open balance
            update_opening_balance(
                payable_charter_account,
                balance_operation_for_action(payable_action),
                payable_request_total_balance,
                0,
            )

            if payment_account is not None:
                # Paying ALWAYS credits the funding account, and that account is
                # user-chosen -- on a credit card (a LIABILITY) "substraction"
                # resolved to DEBIT and both legs landed on the same side.
                payment_action = action_for_side(
                    payment_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    payment_account,
                    balance_operation_for_action(payment_action),
                    payable_request_total_balance,
                    0,
                )
            connector_data.append(
                (
                    payable_charter_account,
                    payable_action,
                    purchase_payment.total,
                    payable_charter_account.opening_balance,
                    None,
                ),
            )

            if payment_account is not None:
                connector_data.append(
                    (
                        payment_account,
                        payment_action,
                        payable_request_total_balance,
                        payment_account.opening_balance,
                        None,
                    ),
                )

        if credit_note_payment_items:
            total_credit_note_amount = 0
            for credit_note_payment_item in credit_note_payment_items:
                credit_note = get_object_or_404(
                    CreditNote.objects.filter(
                        uid=credit_note_payment_item.get("credit_note_uid"),
                        company=company,
                    )
                )
                used_total = credit_note_payment_item.get("used_total")
                item = PurchasePaymentItem.objects.create(
                    purchase_payment=purchase_payment,
                    status=PurchasePaymentItemStatusChoices.DRAFT,
                    model_kind=PurchasePaymentItemModelKindChoices.CREDIT_NOTE,
                    total=credit_note_payment_item.get("total"),
                    used_total=used_total,
                    credit_note=credit_note,
                )
                item.save()

                used_total_decimal = Decimal(used_total)
                total_credit_note_amount += used_total_decimal
                credit_note.total -= used_total_decimal
                if credit_note.total <= 0:
                    credit_note.status = CreditNoteStatusChoices.CLOSE
                else:
                    credit_note.status = CreditNoteStatusChoices.OPEN
                credit_note.save()

            # Update the charter account opening balance
            # update_opening_balance(
            #     inventory_account,
            #     JournalEntryConnectorKindChoices.DEBIT,
            #     total_credit_note_amount,
            #     0,
            # )

            # connector_data.append(
            #     (
            #         inventory_account,
            #         "substraction",
            #         total_credit_note_amount,
            #         inventory_account.opening_balance,
            #         None,
            #     ),
            # )

        journal_entry = JournalEntryService.create_journal_entry(
            amount=payable_request_total_balance,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.PURCHASE_PAYMENT,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=purchase_payment,
        )

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=payable_request_total_balance,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            supplier=supplier,
            created_by=user.get_employee(),
        )

        if tag_title_list:
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.PURCHASE_PAYMENT,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        purchase_payment=purchase_payment,
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
                model_kind=FileItemConnectorModelKindChoices.PURCHASE_PAYMENT,
                object=purchase_payment,
            )

        # Email handling
        email = validated_data.get("email", None)
        supplier_email = (
            email.get("customer_email", supplier.email) if email else supplier.email
        )

        emails = []
        if supplier_email:
            emails.append(supplier_email)
        emails += [email.get("cc_emails", "") if email else ""]
        emails += [email.get("bcc_emails", "") if email else ""]

        # Generate PDF and send email if there's a recipient
        if emails:
            # Set title based on payment
            title = "PAYMENT"
            label = "payments"

            subject = f"Balanzify {title}"
            request = self.context["request"]

            # Generate PDF
            payment_pdf = get_pdf(
                self,
                False,
                {
                    "label": label,
                    "template": "emails/purchases/purchase_payment_pdf_template.html",
                    "title": title,
                    "is_report": False,
                    "data": {
                        "company": company,
                        "supplier": supplier,
                        "full_billing_address": full_billing_address,
                        "supplier_email": supplier_email,
                        "payment": purchase_payment,
                        "payment_items": purchase_payment.purchasepaymentitem_set.all(),
                        "description": validated_data.get("description", ""),
                    },
                },
            )

            # Send email
            send_email_to_user(
                {
                    "title": title,
                    "company": company,
                    "supplier": supplier,
                    "url": file_url(payment_pdf.file, request),
                    "document_type": title,
                },
                "emails/purchases/purchase_payment_email_template.html",
                emails,
                subject,
            )

        return purchase_payment


class PrivateWePurchasePaymentDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    # Supplier related
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )

    # Payment method related
    payment_method = PrivatePaymentMethodSlimSerializer(read_only=True)
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.filter(status=PaymentMethodStatusChoices.ACTIVE),
        write_only=True,
        required=False,
    )

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

    # Address related
    full_billing_address = CharField(write_only=True, required=False)
    billing_address = PrivateAddressSerializer(
        source="addressconnector_set.first.address",
        read_only=True,
    )

    # Tag related
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
        model = PurchasePayment
        fields = [
            "uid",
            "date",
            "email",
            "status",
            "bill_number",
            # Amount related
            "total",
            "deposit",
            "due_total",
            "description",
            # Supplier related
            "supplier",
            "supplier_uid",
            # Payment method related
            "payment_method",
            "payment_method_uid",
            # Payment account related
            "payment_account",
            "payment_account_uid",
            # Address related
            "full_billing_address",
            "billing_address",
            # Tag related
            "tag_title_list",
            # File related
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
    ]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        # `status` is writable here and read-only on none of the six
        # detail serializers, so a PATCH could retire the document by
        # writing the column -- skipping every guard, the reversal and
        # the allocation unwind that live in `perform_destroy`.
        assert_not_retiring_by_patch(
            instance, validated_data, document='supplier payment',
        )

        # The DELETE for this same document has refused a reconciled payment
        # since `931dc167` (`views/purchases.py:881-883`); the edit never did.
        # Below, a change to `total` rewrites `credit`/`total`/`last_balance` in
        # place on the funding leg -- the bank credit `/reconcile/complete`
        # offers to tick -- so the amount a closed statement signed off can be
        # changed underneath it while deleting the very same document is
        # refused.
        assert_not_reconciled(
            JournalEntry.objects.filter(purchase_payment=instance),
            action="change",
        )

        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company
        full_billing_address = validated_data.pop("full_billing_address", None)
        tag_title_list = validated_data.pop("tag_title_list", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        current_total = instance.total
        new_total = validated_data.get("total", current_total)

        supplier = instance.supplier
        if supplier_uid := validated_data.pop("supplier_uid", None):
            supplier = supplier_uid
            validated_data["supplier"] = supplier

        # Payment method update
        if payment_method_uid := validated_data.pop("payment_method_uid", None):
            validated_data["payment_method"] = payment_method_uid

        # Payment account update
        payment_account = instance.payment_account
        if payment_account_uid := validated_data.pop("payment_account_uid", None):
            payment_account = payment_account_uid
            validated_data["payment_account"] = payment_account

        if current_total != new_total:
            chart_of_accounts = get_chart_of_account(
                ["Accounts Payable (A/P)"],
                company,
            )
            payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")

            # Get the entries to be updated
            journal_entry = JournalEntry.objects.filter(
                purchase_payment=instance,
                kind=JournalEntryKindChoices.PURCHASE_PAYMENT,
                company=company,
            ).order_by("id").first()

            if journal_entry:
                journal_entry.amount = new_total
                journal_entry.save()

                journal_entry_items = journal_entry.journalentryconnector_set

                # Update the Accounts Payable entry
                if journal_entry_items.exists():
                    payable_journal_item = journal_entry_items.filter(
                        account=payable_charter_account
                    ).first()
                    if payable_journal_item:
                        # The A/P leg below was hardened to amend on the side
                        # the posting used; the vendor's own balance beside it
                        # was left on "update", which has no account kind to
                        # read and takes its direction from whether the figure
                        # rose. Paying a bill SUBTRACTS from what the vendor is
                        # owed, so raising a payment from 100 to 150 added 50 to
                        # the vendor while A/P correctly subtracted 50 -- an
                        # error of twice the delta, in the opposite direction,
                        # on a journal that still balanced.
                        #
                        # `purchases.py`'s BILL amend keeps "update" and is
                        # right to: a bill CREDITS the vendor balance, so the
                        # signed delta is already the correct rule there. A
                        # sweep that changes both inverts the bill path.
                        if supplier:
                            amend_balance(
                                supplier,
                                JournalEntryConnectorKindChoices.DEBIT,
                                new_total,
                                current_total,
                            )

                        # Paying a bill DEBITS payables, as the connector line
                        # below records. On a liability that SUBTRACTS from the
                        # stored balance.
                        amend_leg(
                            payable_charter_account,
                            JournalEntryConnectorKindChoices.DEBIT,
                            new_total,
                            current_total,
                        )

                        # Update the journal entry item
                        payable_journal_item.debit = new_total
                        payable_journal_item.total = new_total
                        payable_journal_item.last_balance = (
                            payable_charter_account.opening_balance
                        )
                        payable_journal_item.save_dirty_fields()

                if payment_account is not None and journal_entry_items.exists():
                    payment_journal_item = journal_entry_items.filter(
                        account=payment_account
                    ).first()

                    if payment_journal_item:
                        amend_leg(
                            payment_account,
                            JournalEntryConnectorKindChoices.CREDIT,
                            new_total,
                            current_total,
                        )

                        payment_journal_item.credit = new_total
                        payment_journal_item.total = new_total
                        payment_journal_item.last_balance = (
                            payment_account.opening_balance
                        )
                        payment_journal_item.save_dirty_fields()

        if full_billing_address:
            address_connector = instance.addressconnector_set.first()
            if address_connector:
                address_connector.address.full_address = full_billing_address
                address_connector.address.save()
            else:
                AddressConnector.objects.create(
                    address=Address.objects.create(
                        full_address=full_billing_address,
                        company=validated_data["company"],
                    ),
                    kind=AddressConnectorKindCoices.PURCHASE_PAYMENT,
                    purchase_payment=instance,
                )

        if tag_title_list:
            Tag.objects.filter(
                id__in=TagConnector.objects.filter(
                    purchase_payment=instance
                ).values_list("tag_id", flat=True)
            ).delete()

            # Add new tags from the update request
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.PURCHASE_PAYMENT,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        purchase_payment=instance,
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
                model_kind=FileItemConnectorModelKindChoices.PURCHASE_PAYMENT,
                object=instance,
            )

        return super().update(instance, validated_data)


class PrivateWePurchasePaymentItemListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    # Purchase related
    purchase = PrivatePurchaseSlimSerializer(read_only=True)
    purchase_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Purchase.objects.filter(status=PurchaseStatus.OPEN),
        write_only=True,
        required=False,
    )

    # Credit note related
    credit_note = PrivateCreditNoteSlimSerializer(read_only=True)
    credit_note_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CreditNote.objects.filter(status=CreditNoteStatusChoices.OPEN),
        write_only=True,
        required=False,
    )

    def validate(self, validated_data):
        purchase_uid = validated_data.get("purchase_uid")
        credit_note_uid = validated_data.get("credit_note_uid")
        if bool(purchase_uid) == bool(credit_note_uid):
            raise ValidationError(
                {"message": "Please select one among purchase and credit note"}
            )

        elif validated_data.get("status") == PurchasePaymentItemStatusChoices.REMOVED:
            raise ValidationError(
                {"message": "You don't have permission to remove this item."}
            )

        return super().validate(validated_data)

    class Meta:
        model = PurchasePaymentItem
        fields = [
            "uid",
            "status",
            "model_kind",
            "total",
            "used_total",
            # Purchase related
            "purchase",
            "purchase_uid",
            # Credit note related
            "credit_note",
            "credit_note_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "model_kind",
            "created_at",
            "updated_at",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        if purchase_uid := validated_data.pop("purchase_uid", None):
            validated_data["model_kind"] = PurchasePaymentItemModelKindChoices.PURCHASE
            validated_data["purchase"] = purchase_uid

        if credit_note_uid := validated_data.pop("credit_note_uid", None):
            validated_data["model_kind"] = (
                PurchasePaymentItemModelKindChoices.CREDIT_NOTE
            )
            validated_data["credit_note"] = credit_note_uid

        validated_data["purchase_payment"] = get_object_or_404(
            PurchasePayment.objects.filter(
                uid=self.context.get("uid"), company=self.context["request"].user.get_active_company()
            )
        )
        return super().create(validated_data)


class PrivateWePurchasePaymentItemsDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    purchase = PrivatePurchaseSlimSerializer(read_only=True)
    credit_note = PrivateCreditNoteSlimSerializer(read_only=True)
    purchase_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Purchase.objects.all().exclude(status=PurchaseStatus.REMOVED),
        write_only=True,
        required=False,
    )
    credit_note_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CreditNote.objects.all().exclude(
            status=CreditNoteStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )

    class Meta:
        model = PurchasePaymentItem
        fields = [
            "uid",
            "status",
            "model_kind",
            "purchase",
            "credit_note",
            "total",
            "used_total",
            "purchase_uid",
            "credit_note_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "status",
            "model_kind",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        purchase_uid = validated_data.get("purchase_uid")
        credit_note_uid = validated_data.get("credit_note_uid")
        if bool(purchase_uid) == bool(credit_note_uid):
            raise ValidationError(
                {"message": "Please select one among purchase and credit note"}
            )

        elif validated_data.get("status") == PurchasePaymentItemStatusChoices.REMOVED:
            raise ValidationError(
                {"message": "You don't have permission to remove this item."}
            )

        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        if purchase_uid := validated_data.pop("purchase_uid", None):
            validated_data["model_kind"] = PurchasePaymentItemModelKindChoices.PURCHASE
            validated_data["purchase"] = purchase_uid
            validated_data["credit_note"] = None

        if credit_note_uid := validated_data.pop("credit_note_uid", None):
            validated_data["model_kind"] = (
                PurchasePaymentItemModelKindChoices.CREDIT_NOTE
            )
            validated_data["credit_note"] = credit_note_uid
            validated_data["purchase"] = None

        return super().update(instance, validated_data)


class PrivateWePurchaseSettingDetailsSerializer(ModelSerializer):
    class Meta:
        model = PurchaseSetting
        fields = [
            "uid",
            "is_purchase_item",
            "is_tag",
            "is_track_expense_and_items_by_customer",
            "is_expense_and_item_billable",
            "is_purchase_order",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)
