import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

from rest_framework.generics import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import (
    CharField,
    ChoiceField,
    ModelSerializer,
    SlugRelatedField,
    ListField,
    FileField,
    DateField,
    JSONField,
    DecimalField,
)

from django.db import transaction
from django.db.models import Q

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountStatusChoices, ChartOfAccountKindChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices
from addressio.django_rest.serializers.common import PrivateAddressSerializer

from agencyio.django_rest.serializers.common import (
    PrivateAgencyTaxSlimSerializer,
    AgencyTaxSerializer,
    PrivateWeAgencySlimSerializer,
)
from agencyio.models import AgencyTax, Agency

from common.choices import CurrencyChoices
from common.django_rest.helpers.serializer_scoping import CompanyScopedRelatedFieldsMixin
from common.django_rest.helpers.serializer_scoping import company_scoped
from common.django_rest.helpers.retire_guard import assert_not_retiring_by_patch
from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    amend_leg,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.quantity_helpers import update_quantity
from common.django_rest.helpers.fifo_product_quantity_helpers import (
    fifo_product_deduction,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.emails import send_email_to_user
from common.django_rest.helpers.file_helpers import (
    get_pdf,
    file_url,
    link_file_to,
)

from creditnoteio.models import CreditNote
from .creditnotes import PrivateWeCreditNoteDetailsSerializer

from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector

from customerio.models import Customer
from customerio.choices import CustomerStatusChoices
from customerio.django_rest.serializers.common import (
    PrivateCustomerSlimSerializer,
)

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.services.files import FileService

from journalio.models import JournalEntry
from journalio.django_rest.services.journals import JournalEntryService
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)

from productio.models import Product
from productio.django_rest.serializers.common import PrivateProductSlimSerializer

from paymentio.django_rest.serializers.common import PrivatePaymentMethodSlimSerializer
from paymentio.models import PaymentMethod
from paymentio.choices import PaymentMethodStatusChoices


from salesio.models import (
    Sale,
    SaleSetting,
    SaleItem,
    SalePaymentReceive,
    SalePaymentReceiveItem,
    SalesTax,
)
from salesio.choices import (
    SaleItemStatusChoices,
    SalesStatusChoices,
    SaleReceptKindChoices,
    SalePaymentReceiveItemModelStatusChoices,
    SalePaymentReceiveItemModelKindChoices,
    SalesTaxStatusChoices,
)

from tagio.choices import TagStatusChoices, TagKindChoices
from tagio.models import Tag, TagConnector

from termio.choicess import TermStatusChoices, TermKindChoices
from termio.django_rest.serializers.common import PrivateTermSlimSerializer
from termio.models import Term, TermConnector

from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer
from wirehouseio.models import Warehouse

from ..helpers.purchase_item_helpers import get_latest_published_purchase_item
from ..helpers.sale_posting import (
    post_sale_document,
    reconcile_sale_items,
    reverse_sale_postings,
)

from .payment_methods import PrivateWePaymentMethodDetailsSerializer


def resolve_discount_amount(validated_data, total):
    """The discount as a money amount, whichever way it was entered.

    `discount` is a percentage or a flat figure depending on `discount_kind`, so
    it cannot be posted as-is. A 10 on a 1,000 invoice is either 10.00 or 100.00
    and the journal has to know which.

    The percentage applies to the document total. That is the same base the
    frontend computes the displayed discount from, so the journal agrees with
    what the customer was shown.
    """
    from common.choices import DiscountKind

    discount = quantize_money(validated_data.get("discount", 0) or 0)
    if not discount:
        return Decimal("0.00")

    if validated_data.get("discount_kind") == DiscountKind.PERCENTAGE:
        return quantize_money(quantize_money(total or 0) * discount / Decimal("100"))
    return discount


class PrivateWeSaleListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    customer = PrivateCustomerSlimSerializer(read_only=True)
    customer_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Customer.objects.selectable()
        .all()
        .exclude(status=CustomerStatusChoices.REMOVED),
        write_only=True,
    )
    tag_title_list = JSONField(required=False, write_only=True)
    full_billing_address = CharField(write_only=True, required=False)
    full_shipping_address = CharField(write_only=True, required=False)
    shipping_by = CharField(write_only=True, required=False)
    shipping_date = DateField(write_only=True, required=False)
    sales_items = JSONField(required=False, write_only=True)

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
    warehouse = PrivateWarehouseSlimSerializer(read_only=True)
    warehouse_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Warehouse.objects.all(),
        write_only=True,
        required=False,
    )

    # Terms related
    terms = PrivateTermSlimSerializer(
        source="termconnector_set.first.term", required=False, read_only=True
    )
    term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    invoice_id = CharField(read_only=True)
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(
            status=PaymentMethodStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    payment_method = PrivateWePaymentMethodDetailsSerializer(read_only=True)
    receivable_charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    receivable_charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    payable_charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    payable_charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    # Currency related
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=True, write_only=True
    )
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=AgencyTax.objects.all(),
        required=False,
        write_only=True,
    )
    auto_sales_tax = JSONField(required=False, write_only=True)

    class Meta:
        model = Sale
        fields = [
            "uid",
            "invoice_id",
            "date",
            "email",
            "status",
            "kind",
            "tracking_number",
            "reference_number",
            "discount_kind",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "tax_uid",
            "total",
            "deposit",
            "due_total",
            "description",
            "tax_kind",
            "invoice_date",
            "due_date",
            "expired_date",
            "is_invoice",
            "is_estimated",
            "is_sale_receipt",
            "customer",
            "customer_uid",
            "full_billing_address",
            "full_shipping_address",
            "shipping_by",
            "shipping_date",
            "tag_title_list",
            "sales_items",
            "files",
            "file_description",
            "file_uids",
            "warehouse",
            "warehouse_uid",
            "payment_method_uid",
            "payment_method",
            "terms",
            "term_uid",
            "receivable_charter_account_uid",
            "receivable_charter_account",
            "payable_charter_account_uid",
            "payable_charter_account",
            # Crurrency related
            "currency_kind",
            "currency_rate",
            "created_by",
            "created_at",
            "updated_at",
            "auto_sales_tax",
        ]

    read_only_fields = [
        "uid",
        "company",
        "invoice_id",
        "created_by",
        "created_at",
        "updated_at",
    ]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        company = user.get_active_company()
        customer = validated_data.pop("customer_uid", None)
        is_estimated = validated_data.get("is_estimated", False)
        is_invoice = validated_data.get("is_invoice", False)
        is_sale_receipt = validated_data.get("is_sale_receipt", False)
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company
        validated_data["customer"] = customer
        warehouse = validated_data.pop("warehouse_uid", None)
        validated_data["warehouse"] = warehouse
        validated_data["payment_method"] = validated_data.pop(
            "payment_method_uid", None
        )
        # Defaults to SALE, matching the model. Reading None here meant an
        # invoice whose payload omitted `kind` matched neither the SALE nor the
        # REFUND branch, so the Sale row, its items, the FIFO deduction and the
        # balance mutations were all committed with NO journal entry at all --
        # the row itself still got SALE from the model default, so nothing
        # downstream looked wrong.
        kind = validated_data.get("kind") or SaleReceptKindChoices.SALE
        title = "INVOICE"
        label = "invoice"
        tracking_number = validated_data["tracking_number"] = get_unique_id(
            Sale, company.id, "tracking_number", "INV"
        )
        reference_number = validated_data.get(
            "reference_number",
            get_unique_id(
                Sale,
                company.id,
                "tracking_number",
                "REF-INV",
            ),
        )
        due_date = validated_data.get("due_date", "")
        if is_estimated == True:
            title = "ESTIMATE"
            label = "estimate"
            due_date = validated_data["expired_date"]
        elif is_sale_receipt:
            tracking_number = validated_data["tracking_number"] = tracking_number = (
                validated_data["tracking_number"]
            ) = get_unique_id(Sale, company.id, "tracking_number", "SR")
            reference_number = validated_data.get(
                "reference_number",
                get_unique_id(
                    Sale,
                    company.id,
                    "tracking_number",
                    "REF-SR",
                ),
            )
            title = "SALE RECEIPT"
            label = "sale_receipt"
            if kind == SaleReceptKindChoices.REFUND:
                title = "REFUND RECEIPT"
                label = "refund_receipt"
                tracking_number = validated_data["tracking_number"] = (
                    tracking_number
                ) = validated_data["tracking_number"] = get_unique_id(
                    Sale, company.id, "tracking_number", "RR"
                )
                reference_number = validated_data.get(
                    "reference_number",
                    get_unique_id(
                        Sale,
                        company.id,
                        "tracking_number",
                        "REF-RR",
                    ),
                )

        validated_data["invoice_id"] = tracking_number
        chart_of_accounts = get_chart_of_account(
            ["Accounts Receivable (A/R)", "Sales Tax Payable", "Undeposited Funds"],
            company,
        )
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        undeposited_funds_account = chart_of_accounts.get("Undeposited Funds")
        # payable_account = chart_of_accounts.get("Sales Tax Payable")
        term = validated_data.pop("term_uid", None)
        receivable_charter_account = validated_data.pop(
            "receivable_charter_account_uid", None
        )
        validated_data["receivable_charter_account"] = receivable_charter_account
        payable_charter_account = validated_data.pop(
            "payable_charter_account_uid", None
        )
        validated_data["payable_charter_account"] = payable_charter_account
        # Popped, not left in place. `tax_uid` is declared on this serializer
        # (:236) and listed in `Meta.fields`, so DRF validates it into
        # `validated_data` -- and `create()` ends in
        # `Sale.objects.create(**validated_data)`, which rejects any key that is
        # not a model field:
        #
        #     TypeError: Sale() got unexpected keyword arguments: 'tax_uid'
        #
        # A 500 on `POST /we/sales` for any client that sends a document-level
        # tax. The pop was here and commented out.
        #
        # Discarded rather than stored, because there is nowhere to store it:
        # `tax` is a field on SaleItem, not on Sale. The tax that actually posts
        # comes from each line's own `tax_uid` (see the per-item lookup below,
        # which binds its own `sales_taxes`), and anything the lines do not
        # account for is picked up from the header `total_tax` by
        # `_post_unattributed_tax`. So the document-level value is redundant
        # with both -- accepted for the client's convenience, used by neither.
        validated_data.pop("tax_uid", None)
        auto_sales_tax_data = validated_data.pop("auto_sales_tax", None)
        logger.info("auto_sales_tax_data from serializer: %s", auto_sales_tax_data)
        # Defaults to SALE, matching the model. Reading None here meant an
        # invoice whose payload omitted `kind` matched neither the SALE nor the
        # REFUND branch, so the Sale row, its items, the FIFO deduction and the
        # balance mutations were all committed with NO journal entry at all --
        # the row itself still got SALE from the model default, so nothing
        # downstream looked wrong.
        kind = validated_data.get("kind") or SaleReceptKindChoices.SALE
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        tag_title_list = validated_data.pop("tag_title_list", None)
        full_billing_address = validated_data.pop("full_billing_address", None)
        full_shipping_address = validated_data.pop("full_shipping_address", None)
        shipping_by = validated_data.pop("shipping_by", None)
        shipping_date = validated_data.pop("shipping_date", None)
        sales_items = validated_data.pop("sales_items", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        email = validated_data.get("email", None)
        customer_email = email.get("customer_email", customer.email)
        emails = []
        emails.append(customer_email)
        emails += [email.get("cc_emails", "")]
        emails += [email.get("bcc_emails", "")]
        connector_data = []

        # Creating sale
        sale = Sale.objects.create(**validated_data)

        # Save auto_sales_tax JSON data if provided from frontend
        if auto_sales_tax_data:
            sale.auto_sales_tax = auto_sales_tax_data
            sale.save(update_fields=["auto_sales_tax"])

        if term:
            TermConnector.objects.create(
                kind=TermKindChoices.SALE,
                sale=sale,
                term=term,
            )

        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=user.get_active_company(),
        )

        CurrencyConnector.objects.create(
            currency=currency,
            model_kind=CurrencyConnectorModelKind.SALE,
            sale=sale,
        )

        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address=full_billing_address, company=validated_data["company"]
            ),
            sale=sale,
            kind=AddressConnectorKindCoices.SALE,
        )

        if shipping_date and shipping_by:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_shipping_address,
                    shipping_by=shipping_by,
                    shipping_date=shipping_date,
                    is_shipping=True,
                    company=validated_data["company"],
                ),
                sale=sale,
                kind=AddressConnectorKindCoices.SALE,
            )

        if tag_title_list:
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.SALE,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        sale=sale,
                    )
                    for tag_item in tag_items
                ]
            )

        if sales_items:
            items = []
            for sale_item in sales_items:
                product = get_object_or_404(
                    company_scoped(Product.objects.filter(uid=sale_item.get("product_uid")), self)
                )
                is_tax = sale_item.get("is_tax", sale_item.get("is_item_tax", False))
                # if product.quantity < sale_item.get("quantity", 0):
                #     raise ValidationError("Quantity is less")
                sales_taxes = (
                    get_object_or_404(
                        AgencyTax.objects.filter(
                            uid=sale_item.get("tax_uid"), company=company
                        )
                    )
                    if sale_item.get("tax_uid")
                    else None
                )

                # Ensure accounts exist before using them
                product_income_account = product.income_account
                product_asset_account = product.asset_account

                current_sale_item = SaleItem(
                    sale=sale,
                    section=sale_item.get("section", None),
                    note=sale_item.get("note", None),
                    status=SaleItemStatusChoices.PUBLISHED,
                    quantity=sale_item.get("quantity", 0),
                    total=sale_item.get("total", 0),
                    sale_price=sale_item.get("sale_price", 0),
                    description=sale_item.get("description", None),
                    is_tax=is_tax,
                    # tax=sales_taxes if is_tax else None,
                    tax=sales_taxes,
                    product=product,
                )

                items.append(current_sale_item)

            # The lines are persisted before anything posts, because the
            # poster reads them back from the database -- and because they used
            # to be created last, after the posting loop, which left every sale
            # movement in the stock ledger with `sale_item=NULL` and so no way
            # to attribute per-lot cost to the line that caused it.
            SaleItem.objects.bulk_create(items)

        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.SALE,
                object=sale,
            )
        # --- Posting ------------------------------------------------------
        # Everything this document puts in the ledger is emitted by
        # post_sale_document(), which reads the sale and its lines back from the
        # database instead of the payload.
        #
        # It used to be ~590 lines inline here, and update() carried its own
        # separate implementation that patched those rows afterwards. Two
        # implementations of one posting could not agree, and did not: an
        # amended invoice and a freshly entered one with identical contents
        # produced different ledgers. One function, called by both, is what
        # makes them the same document.
        post_sale_document(sale, created_by=user.get_employee())

        # Email sending
        if is_invoice == True or is_estimated == True or is_sale_receipt == True:
            customer_address = customer.addressconnector_set.first()
            subject = f"Balanzify {title}"
            invoice = get_pdf(
                self,
                False,
                {
                    "label": label,
                    # "template": "emails/invoices/invoice_email_template.html",
                    "template": "emails/invoices/invoice_pdf_template.html",
                    "title": title,
                    "is_report": False,
                    "data": {
                        "company": company,
                        "customer": customer,
                        "customer_address": (
                            customer_address.address if customer_address else ""
                        ),
                        "customer_email": customer_email,
                        "billing_address": full_billing_address,
                        "shipping_address": full_shipping_address,
                        "shipping_date": shipping_date,
                        "shipping_by": shipping_by,
                        "tracking_number": tracking_number,
                        "reference_number": reference_number,
                        "invoice_date": validated_data.get("invoice_date", ""),
                        "date": sale.date,
                        "deposit_to": receivable_charter_account,
                        "refund_from": payable_charter_account,
                        "kind": kind,
                        "payment_method": validated_data.get("payment_method"),
                        "location": warehouse.title if warehouse else "",
                        "invoice_due_date": due_date,
                        "term": term,
                        "description": validated_data.get("description", ""),
                        "total_tax": validated_data.get("total_tax", 0.00),
                        "deposit": validated_data.get("deposit", 0.00),
                        "total": validated_data.get("total", 0.00),
                        "due_total": validated_data.get("due_total", 0.00),
                        "sale_items": SaleItem.objects.filter(sale=sale),
                    },
                },
            )
            # Attach the PDF to the sale, otherwise it is orphaned in storage
            # and the document's Download action finds nothing.
            link_file_to(invoice, sale, FileItemConnectorModelKindChoices.SALE)

            # Deferred until the transaction commits, for two reasons: an SMTP
            # call inside a transaction pins a database connection for its whole
            # duration, and a send that succeeds inside a transaction that later
            # rolls back means the customer holds an invoice for a sale that
            # does not exist.
            email_context = {
                "title": title,
                "company": company,
                "customer": customer,
                "url": file_url(invoice.file, request),
            }
            transaction.on_commit(
                lambda: send_email_to_user(
                    email_context,
                    "emails/invoices/invoice_email_template.html",
                    emails,
                    subject,
                )
            )
        return sale


class PrivateWeSaleDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    warehouse = PrivateWarehouseSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    billing_address = PrivateAddressSerializer(
        source="addressconnector_set.last.address",
        read_only=True,
    )
    shipping_address = PrivateAddressSerializer(
        source="addressconnector_set.first.address",
        read_only=True,
    )
    sales_items = JSONField(required=False, write_only=True)
    tag_title_list = JSONField(required=False, write_only=True)
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
    term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    terms = PrivateTermSlimSerializer(
        source="termconnector_set.first.term", required=False, read_only=True
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
    receivable_charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    receivable_charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    payable_charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    payable_charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    # Adress related
    full_shipping_address = CharField(write_only=True, required=False)
    shipping_by = CharField(write_only=True, required=False)
    shipping_date = DateField(write_only=True, required=False)
    auto_sales_tax = JSONField(required=False, write_only=True)

    class Meta:
        model = Sale
        fields = [
            "uid",
            "invoice_id",
            "date",
            "email",
            "status",
            "kind",
            "tracking_number",
            "reference_number",
            "discount_kind",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "total",
            "deposit",
            "due_total",
            "description",
            "tax_kind",
            "invoice_date",
            "due_date",
            "expired_date",
            "is_invoice",
            "is_estimated",
            "is_sale_receipt",
            "customer",
            "billing_address",
            "shipping_address",
            "warehouse",
            "payment_method_uid",
            "payment_method",
            "sales_items",
            "tag_title_list",
            "files",
            "file_description",
            "file_uids",
            "warehouse_uid",
            "term_uid",
            "terms",
            "receivable_charter_account",
            "receivable_charter_account_uid",
            "payable_charter_account",
            "payable_charter_account_uid",
            # Address related
            "full_shipping_address",
            "shipping_by",
            "shipping_date",
            "created_by",
            "created_at",
            "updated_at",
            "auto_sales_tax",
        ]

    read_only_fields = [
        "uid",
        "invoice_id",
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
            instance, validated_data, document='sale',
        )

        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["company"] = company
        user = self.context["request"].user
        sales_items = validated_data.pop("sales_items", None)
        tag_titles = validated_data.pop("tag_title_list", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)
        term = validated_data.pop("term_uid", None)
        auto_sales_tax_data = validated_data.pop("auto_sales_tax", None)

        # Save auto_sales_tax JSON data if provided from frontend (update)
        if auto_sales_tax_data:
            logger.info("auto_sales_tax_data payload (UPDATE): %s", auto_sales_tax_data)
            instance.auto_sales_tax = auto_sales_tax_data
            instance.save(update_fields=["auto_sales_tax"])

        # Address related
        full_shipping_address = validated_data.pop("full_shipping_address", "")
        shipping_by = validated_data.pop("shipping_by", "")
        shipping_date = validated_data.pop(
            "shipping_date", datetime.today().strftime("%Y-%m-%d")
        )

        # Only overwrite these when the payload actually carried them.
        #
        # They used to be popped with a None default and then assigned
        # unconditionally, so a PATCH that did not resend warehouse_uid cleared
        # the sale's warehouse, and one that did not resend the charter-account
        # uids cleared the account the deposit or refund posts to -- silently
        # dropping that leg from the ledger on the next post.
        if "warehouse_uid" in validated_data:
            validated_data["warehouse"] = validated_data.pop("warehouse_uid")
        if "receivable_charter_account_uid" in validated_data:
            validated_data["receivable_charter_account"] = validated_data.pop(
                "receivable_charter_account_uid"
            )
        if "payable_charter_account_uid" in validated_data:
            validated_data["payable_charter_account"] = validated_data.pop(
                "payable_charter_account_uid"
            )

        # --- Reverse ------------------------------------------------------
        # Refused first, because the reverse below DELETES this document's
        # entries and `JournalEntryConnector.journal` is CASCADE -- so amending
        # a sale destroys every leg it posted, `reconciliation` and `cleared_on`
        # included. A closed session would keep its zero `difference` while the
        # lines it was computed against stopped existing, and nothing would say
        # so. This is the sharpest instance of the reconciled-immutability gap:
        # the guard the delete paths take refuses a rewrite; here it refuses an
        # erasure.
        assert_not_reconciled(
            JournalEntry.objects.filter(sale=instance), action="change"
        )

        # Done FIRST, while `instance` still holds the values the document was
        # posted with -- super().update() below is what replaces them.
        reversal = reverse_sale_postings(instance)

        if term is not None:
            term_connector = instance.termconnector_set.first()
            if term_connector:
                term_connector.term = term
                term_connector.save()
            else:
                TermConnector.objects.create(
                    kind=TermKindChoices.SALE,
                    sale=instance,
                    term=term,
                )

        if tag_titles:
            Tag.objects.filter(
                id__in=TagConnector.objects.filter(sale=instance).values_list(
                    "tag_id", flat=True
                )
            ).delete()

            # Add new tags from the update request
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.SALE,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_titles
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        sale=instance,
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
                model_kind=FileItemConnectorModelKindChoices.SALE,
                object=instance,
            )

        # Updatating addreses
        address_connector = instance.addressconnector_set.first()
        if address_connector is not None:
            address_connector.address.full_address = full_shipping_address
            address_connector.address.shipping_by = shipping_by
            address_connector.address.shipping_date = shipping_date
            address_connector.address.save()
        else:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_shipping_address,
                    shipping_by=shipping_by,
                    shipping_date=shipping_date,
                    is_shipping=True,
                    company=validated_data["company"],
                ),
                sale=instance,
                kind=AddressConnectorKindCoices.SALE,
            )
        # --- Repost -------------------------------------------------------
        # Amendment used to be patch-in-place: find the connector rows written
        # last time, assign recomputed amounts onto them, and nudge
        # opening_balance by a delta worked out on the fly. That cannot be made
        # correct by adding cases, because what must change is not a function of
        # what the payload happens to contain -- a price-only edit moved A/R and
        # left income alone; a line spanning three lots had one of its three
        # rows rewritten; a line deleted in the grid was never visited at all,
        # so its revenue, cost and inventory relief stayed live; and the tax
        # breakdown was walked twice, posting the same amounts again as if fresh.
        #
        # The document is now reversed in full and posted again from what it
        # persists, by the same function that posts a brand-new sale. An amended
        # sale and a freshly entered one with the same contents are therefore
        # the same document in the ledger.
        instance = super().update(instance, validated_data)

        reconciliation = reconcile_sale_items(
            instance,
            sales_items,
            product_for=lambda payload: (
                get_object_or_404(
                    company_scoped(Product.objects.filter(uid=payload.get("product_uid")), self)
                )
                if payload.get("product_uid")
                else None
            ),
        )

        journal_entry = post_sale_document(
            instance,
            created_by=user.get_employee(),
            request_kind=JournalEntryConnectorRequestKindChoices.UPDATED,
        )
        logger.info(
            "sale %s amended: reversed %s, lines %s, reposted entry %s",
            instance.pk,
            reversal,
            reconciliation,
            getattr(journal_entry, "pk", None),
        )
        return instance


class PrivateWeSalesItemListSerializer(ModelSerializer):
    product = PrivateProductSlimSerializer(read_only=True)
    tax = AgencyTaxSerializer(read_only=True)
    quantity = CharField(source="get_quantity", read_only=True)
    total = CharField(source="get_total", read_only=True)
    auto_sales_tax = JSONField(source="sale.auto_sales_tax", read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "uid",
            "section",
            "note",
            "quantity",
            "status",
            "total",
            "sale_price",
            "description",
            "product",
            "tax",
            "refund_quantity",
            "refund_status",
            "refund_total",
            "auto_sales_tax",
            "created_at",
            "updated_at",
        ]


class PrivateWeSalesItemDetailsSerializer(ModelSerializer):
    product = PrivateProductSlimSerializer(read_only=True)
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)
    quantity = CharField(source="get_quantity", read_only=True)
    total = CharField(source="get_total", read_only=True)
    auto_sales_tax = JSONField(source="sale.auto_sales_tax", read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "uid",
            "section",
            "note",
            "quantity",
            "status",
            "total",
            "sale_price",
            "description",
            "product",
            "tax",
            "refund_quantity",
            "refund_status",
            "refund_total",
            "auto_sales_tax",
            "created_at",
            "updated_at",
        ]


class PrivateWeSalePaymentReceiveListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    customer_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Customer.objects.selectable()
        .all()
        .exclude(status=CustomerStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=True, write_only=True
    )
    full_billing_address = CharField(write_only=True, required=False)
    sale_payment_receive_items = JSONField(required=False, write_only=True)
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(
            status=PaymentMethodStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    deposit_to_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    amount_to_credit = DecimalField(
        max_digits=10, decimal_places=5, required=False, write_only=True
    )
    file_description = CharField(required=False)
    file_uids = JSONField(required=False, write_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    payment_method = PrivateWePaymentMethodDetailsSerializer(read_only=True)
    deposit_to = PrivateChartOfAccountSlimSerializer(read_only=True)

    class Meta:
        model = SalePaymentReceive
        fields = [
            "uid",
            "date",
            "email",
            "status",
            "reference_number",
            "total",
            "deposit",
            "due_total",
            "description",
            "payment_method",
            "payment_method_uid",
            "customer",
            "customer_uid",
            "deposit_to",
            "deposit_to_uid",
            "sale_payment_receive_items",
            "full_billing_address",
            "files",
            "file_description",
            "file_uids",
            # Crurrency related
            "currency_kind",
            "currency_rate",
            "amount_to_credit",
        ]

    read_only_fields = ["uid", "created_by", "updated_at"]

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
        validated_data["payment_method"] = validated_data.pop(
            "payment_method_uid", None
        )
        deposit_to = validated_data.pop("deposit_to_uid", None)
        validated_data["deposit_to"] = deposit_to
        total = validated_data["total"]
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        amount_to_credit = validated_data.pop("amount_to_credit", 0.00)
        full_billing_address = validated_data.pop("full_billing_address", None)
        sale_payment_receive_items = validated_data.pop(
            "sale_payment_receive_items", None
        )
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)

        chart_of_accounts = get_chart_of_account(
            ["Accounts Receivable (A/R)"],
            company,
        )
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        email = validated_data.get("email", None)
        customer_email = email.get("customer_email", customer.email)
        emails = []
        emails.append(customer_email)
        emails += [email.get("cc_emails", "")]
        emails += [email.get("bcc_emails", "")]
        connector_data = []
        sale_payment_receive = super().create(validated_data)

        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=user.get_active_company(),
        )

        CurrencyConnector.objects.create(
            currency=currency,
            model_kind=CurrencyConnectorModelKind.SALE_PAYMENT_RECEIVE,
            sale_payment_receive=sale_payment_receive,
        )

        if full_billing_address:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_billing_address, company=validated_data["company"]
                ),
                sale_payment_receive=sale_payment_receive,
                kind=AddressConnectorKindCoices.SALE_PAYMENT_RECEIVE,
            )

        if sale_payment_receive_items:
            for item in sale_payment_receive_items:
                if (
                    item.get("model_kind")
                    == SalePaymentReceiveItemModelKindChoices.SALE
                ):
                    sale = get_object_or_404(
                        company_scoped(Sale.objects.filter(uid=item.get("sale_uid")), self)
                    )

                    sale.apply_sale_payment(item.get("used_total"))

                    payment_status = (
                        SalePaymentReceiveItemModelStatusChoices.COMPLETED
                        if sale.due_total == 0
                        else SalePaymentReceiveItemModelStatusChoices.PARTIALLY
                    )

                    sale_payment_receive_item = SalePaymentReceiveItem.objects.create(
                        sale_payment_receive=sale_payment_receive,
                        status=payment_status,
                        model_kind=item.get(
                            "model_kind", SalePaymentReceiveItemModelKindChoices.SALE
                        ),
                        total=item.get("total"),
                        used_total=item.get("used_total"),
                        sale=sale,
                    )
                    sale_payment_receive_item.save()

                    if sale.due_total == 0:
                        sale.status = SalesStatusChoices.PAID
                        sale.save()

                    sale.save()

                if (
                    item.get("model_kind")
                    == SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE
                ):
                    sale_payment_receive_item = SalePaymentReceiveItem.objects.create(
                        sale_payment_receive=sale_payment_receive,
                        status=item.get(
                            "status", SalePaymentReceiveItemModelStatusChoices.DRAFT
                        ),
                        model_kind=item.get(
                            "model_kind",
                            SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE,
                        ),
                        total=item.get("total"),
                        used_total=item.get("used_total"),
                        credit_note=get_object_or_404(
                            CreditNote.objects.filter(
                                uid=item.get("credit_note_uid"), company=company
                            )
                        ),
                    )
                    sale_payment_receive_item.save()

        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.SALE_PAYMENT_RECEIVE,
                object=sale_payment_receive,
            )

        update_opening_balance(
            customer,
            "debit",
            total,
            0,
        )

        # A payment received CREDITS the receivable -- the customer owes less --
        # and DEBITS wherever the money lands. Both sides are fixed by the
        # transaction and both accounts are user-chosen, so neither can be
        # assumed to be an asset.
        receivable_action = action_for_side(
            receivable_account.kind, JournalEntryConnectorKindChoices.CREDIT
        )
        update_opening_balance(
            receivable_account,
            balance_operation_for_action(receivable_action),
            total,
            0,
        )

        connector_data.append(
            (
                receivable_account,
                receivable_action,
                total,
                receivable_account.opening_balance,
                None,
            )
        )
        # `total`, not `deposit`. The balance move here used `deposit_total`
        # while the connector beside it, the entry's own amount and the
        # connector total all used `total` -- so on any payment where the two
        # payload fields differ, this account's stored balance moved by one
        # figure and its journal line recorded another. `deposit_total` was
        # read exactly once in this method, here.
        deposit_action = action_for_side(
            deposit_to.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            deposit_to,
            balance_operation_for_action(deposit_action),
            total,
            0,
        )

        connector_data.append(
            (
                deposit_to,
                deposit_action,
                total,
                deposit_to.opening_balance,
                None,
            )
        )

        # Creating journal entry
        journal_entry = JournalEntryService.create_journal_entry(
            amount=validated_data["total"],
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE_PAYMENT_RECEIVE,
            is_transaction=False,
            is_journal_entry=True,
            company=company,
            object=sale_payment_receive,
        )
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            customer=customer,
            created_by=user.get_employee(),
        )

        # Email sending
        title = "PAYMENT RECEIVE"
        subject = f"Balanzify {title}"
        payment_receive_pdf = get_pdf(
            self,
            False,
            {
                "label": "payment_receive",
                "template": "emails/sale_payments/payment_receive_pdft_emplate.html",
                "title": title,
                "is_report": False,
                "data": {
                    "company": company,
                    "customer": customer,
                    "full_billing_address": full_billing_address,
                    "customer_email": customer_email,
                    "deposit_to": deposit_to,
                    "reference_number": validated_data.get("reference_number", ""),
                    "payment_received_date": sale_payment_receive.date,
                    "payment_method": validated_data["payment_method"],
                    "total_received": validated_data.get("total", 0.00),
                    "description": validated_data.get("description", ""),
                    "amount_apply": validated_data.get("deposit", 0.00),
                    "amount_to_credit": amount_to_credit,
                    "sale_items": sale_payment_receive.salepaymentreceiveitem_set.filter(
                        model_kind=SalePaymentReceiveItemModelKindChoices.SALE
                    ),
                    "credit_note_items": sale_payment_receive.salepaymentreceiveitem_set.filter(
                        model_kind=SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE
                    ),
                },
            },
        )
        send_email_to_user(
            {
                "title": title,
                "company": company,
                "customer": customer,
                "url": file_url(payment_receive_pdf.file, request),
            },
            "emails/sale_payments/payment_receive_email_template.html",
            emails,
            subject,
        )
        return sale_payment_receive


class PrivateWeSalePaymentReceiveDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    currency_kind = ChoiceField(choices=CurrencyChoices.choices, write_only=True)
    currency_rate = DecimalField(
        max_digits=10, decimal_places=5, required=True, write_only=True
    )
    full_billing_address = CharField(write_only=True, required=False)
    sale_payment_receive_items = JSONField(required=False, write_only=True)
    payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(
            status=PaymentMethodStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    deposit_to_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
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
    customer = PrivateCustomerSlimSerializer(read_only=True)
    payment_method = PrivateWePaymentMethodDetailsSerializer(read_only=True)
    deposit_to = PrivateChartOfAccountSlimSerializer(read_only=True)
    billing_address = PrivateAddressSerializer(
        source="addressconnector_set.first.address",
        read_only=True,
    )

    class Meta:
        model = SalePaymentReceive
        fields = [
            "uid",
            "date",
            "email",
            "status",
            "reference_number",
            "total",
            "deposit",
            "due_total",
            "description",
            "payment_method",
            "payment_method_uid",
            "customer",
            "deposit_to",
            "deposit_to_uid",
            "sale_payment_receive_items",
            "full_billing_address",
            "files",
            "file_description",
            "file_uids",
            # Crurrency related
            "currency_kind",
            "currency_rate",
            "billing_address",
        ]

    read_only_fields = ["uid", "created_at", "updated_at"]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        # `status` is writable here and read-only on none of the six
        # detail serializers, so a PATCH could retire the document by
        # writing the column -- skipping every guard, the reversal and
        # the allocation unwind that live in `perform_destroy`.
        assert_not_retiring_by_patch(
            instance, validated_data, document='customer payment',
        )

        user = self.context["request"].user
        validated_data["created_by"] = user.get_employee()
        company = user.get_active_company()
        validated_data["company"] = company
        currency_kind = validated_data.pop("currency_kind", None)
        currency_rate = validated_data.pop("currency_rate", None)
        full_billing_address = validated_data.pop("full_billing_address", None)
        sale_payment_receive_items = validated_data.pop(
            "sale_payment_receive_items", None
        )
        chart_of_accounts = get_chart_of_account(
            ["Accounts Receivable (A/R)"],
            company,
        )
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        journal_entry = JournalEntry.objects.filter(
            sale_payment_receive=instance
        ).first()
        journal_entry_items = journal_entry.journalentryconnector_set
        connector_data = []
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        file_uids = validated_data.pop("file_uids", None)

        validated_data["payment_method"] = (
            validated_data.pop("payment_method_uid", None) or instance.payment_method
        )
        deposit_to = validated_data.pop("deposit_to_uid", None) or instance.deposit_to
        validated_data["deposit_to"] = deposit_to

        if currency_kind or currency_rate:
            currency, _ = Currency.objects.get_or_create(
                kind=currency_kind,
                exchange_rate=currency_rate,
                company=user.get_active_company(),
            )
            CurrencyConnector.objects.create(
                currency=currency,
                model_kind=CurrencyConnectorModelKind.SALE_PAYMENT_RECEIVE,
                sale_payment_receive=instance,
            )

        if full_billing_address:
            address_connector = instance.addressconnector_set.first()
            if address_connector:
                address_connector.address.full_address = full_billing_address
                address_connector.address.save()
            else:
                AddressConnector.objects.create(
                    address=Address.objects.create(
                        full_address=full_billing_address, company=instance.company
                    ),
                    sale_payment_receive=instance,
                    kind=AddressConnectorKindCoices.SALE_PAYMENT_RECEIVE,
                )

        if sale_payment_receive_items:
            for item in sale_payment_receive_items:
                if item.get("model_kind") == "SALE":
                    sale = get_object_or_404(
                        company_scoped(Sale.objects.filter(uid=item.get("sale_uid")), self)
                    )
                    sale_payment_receive_item = SalePaymentReceiveItem.objects.create(
                        sale_payment_receive=instance,
                        status=item.get(
                            "status", SalePaymentReceiveItemModelStatusChoices.DRAFT
                        ),
                        model_kind=item.get(
                            "model_kind", SalePaymentReceiveItemModelKindChoices.SALE
                        ),
                        total=item.get("total"),
                        used_total=item.get("used_total"),
                        sale=sale,
                    )
                    sale_payment_receive_item.save()
                    sale.apply_sale_payment(item.get("used_total"))
                    sale.save()

                if item.get("model_kind") == "CREDIT_NOTE":
                    sale_payment_receive_item = SalePaymentReceiveItem.objects.create(
                        sale_payment_receive=instance,
                        status=item.get(
                            "status", SalePaymentReceiveItemModelStatusChoices.DRAFT
                        ),
                        model_kind=item.get(
                            "model_kind",
                            SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE,
                        ),
                        total=item.get("total"),
                        used_total=item.get("used_total"),
                        credit_note=get_object_or_404(
                            CreditNote.objects.filter(
                                uid=item.get("credit_note_uid"), company=company
                            )
                        ),
                    )
                    sale_payment_receive_item.save()

        if files or file_uids:
            FileService.create_file_item_connector(
                files=files,
                file_uids=file_uids,
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.SALE_PAYMENT_RECEIVE,
                object=instance,
            )
        # Both legs amend on the side the posting used -- CREDIT the receivable,
        # DEBIT the deposit -- so raising a payment moves each further the way it
        # already went and lowering one walks it back. The "update" op these used
        # instead decided the direction from whether the figure rose or fell,
        # which inverted the receivable leg on every account kind.
        receivable_amend = amend_leg(
            receivable_account,
            JournalEntryConnectorKindChoices.CREDIT,
            validated_data["total"],
            instance.total,
        )
        if journal_entry_items and receivable_amend:
            receivable_action, receivable_amount = receivable_amend
            connector_data.append(
                (
                    receivable_account,
                    receivable_action,
                    receivable_amount,
                    # This used to read `.opening_balance` as an attribute off
                    # the dict `update_opening_balance` returns, so amending a
                    # payment's total raised AttributeError before it could
                    # write anything.
                    receivable_account.opening_balance,
                    journal_entry_items.filter(
                        account=receivable_account,
                        request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                    ).first(),
                )
            )

        # `total` on both legs, because the posting put `total` on both. This
        # amended the deposit leg by the change in `deposit` instead, so any
        # edit that moved the two fields by different amounts left the entry
        # unbalanced -- the receivable leg had moved by one figure and its
        # counterpart by another.
        deposit_amend = amend_leg(
            deposit_to,
            JournalEntryConnectorKindChoices.DEBIT,
            validated_data["total"],
            instance.total,
        )
        if journal_entry_items and deposit_amend:
            deposit_amend_action, deposit_amend_amount = deposit_amend
            connector_data.append(
                (
                    deposit_to,
                    deposit_amend_action,
                    deposit_amend_amount,
                    deposit_to.opening_balance,
                    journal_entry_items.filter(
                        account=deposit_to,
                        request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                    ).first(),
                )
            )
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=validated_data["total"],
            request_kind=JournalEntryConnectorRequestKindChoices.UPDATED,
            journal_entry=journal_entry,
            customer=instance.customer,
            created_by=user.get_employee(),
        )
        return super().update(instance, validated_data)


class PrivateWeSalesPaymentReceiveItemListSerializer(ModelSerializer):
    sale_payment_receive = PrivateWeSalePaymentReceiveDetailsSerializer(read_only=True)
    sale = PrivateWeSaleDetailsSerializer(read_only=True)
    credit_note = PrivateWeCreditNoteDetailsSerializer(read_only=True)

    class Meta:
        model = SalePaymentReceiveItem
        fields = [
            "uid",
            "status",
            "model_kind",
            "sale_payment_receive",
            "sale",
            "credit_note",
            "created_at",
            "updated_at",
        ]


class PrivateWeSaleSettingDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    # Term related
    prefered_term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    prefered_term = PrivateTermSlimSerializer(read_only=True)

    # Payment method related
    prefered_payment_method_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all().exclude(status=TermStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    prefered_payment_method = PrivatePaymentMethodSlimSerializer(read_only=True)

    class Meta:
        model = SaleSetting
        fields = [
            "uid",
            # Sales from content
            "preferred_delivery_method",
            "is_shipping",
            "is_customer_transaction_number",
            "is_service_date",
            "is_discount",
            "is_deposit",
            "is_tag",
            # Invoice payments
            "invoice_payment",
            # Product and services
            "is_product_and_service",
            "is_sku",
            "is_quantity_and_price",
            "is_available_stock",
            # Reminders
            "is_reminder",
            # Statements
            "is_show_transactions_as_single_line",
            "is_include_transaction_details",
            "prefered_term_uid",
            "prefered_term",
            "prefered_payment_method_uid",
            "prefered_payment_method",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        if prefered_term := validated_data.pop("prefered_term_uid", None):
            validated_data["prefered_term"] = prefered_term

        if prefered_payment_method := validated_data.pop(
            "prefered_payment_method_uid", None
        ):
            validated_data["prefered_payment_method"] = prefered_payment_method
        return super().update(instance, validated_data)


class PrivateWeSalesTaxListCreateSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    agency = PrivateWeAgencySlimSerializer(read_only=True)
    agency_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Agency.objects.get_status_all(),
        write_only=True,
        required=False,
    )
    charter_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .all()
        .exclude(status=ChartOfAccountStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    charter_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    class Meta:
        model = SalesTax
        fields = [
            "uid",
            "sales_tax_period",
            "sales_tax_due_date",
            "total_sales_tax",
            "status",
            "agency",
            "agency_uid",
            "charter_account_uid",
            "charter_account",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "company", "created_by", "created_at", "updated_at"]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        company = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company
        total_tax = validated_data.get("total_sales_tax", 0)
        validated_data["status"] = SalesTaxStatusChoices.PAID
        agency = validated_data.pop("agency_uid", None)
        validated_data["agency"] = agency
        chart_of_accounts = get_chart_of_account(
            [
                "Sales Tax Payable",
            ],
            company,
        )
        sales_tax_account = chart_of_accounts.get("Sales Tax Payable")
        charter_account = validated_data.pop("charter_account_uid", None)
        validated_data["charter_account"] = charter_account
        sales_tax = super().create(validated_data)
        connector_data = []

        # Paying sales tax DEBITS the liability -- the debt goes down -- and
        # CREDITS the account it is paid from. Both legs used to hard-code
        # `"substraction"`, which gives those sides only for a liability and an
        # asset respectively, and both paired it with
        # `update_opening_balance(..., "credit", ...)`, which ADDS. So the
        # journal recorded the payment correctly while the stored balances
        # moved the opposite way: paying the tax pushed the liability UP and
        # the bank UP.
        if sales_tax_account:
            tax_action = action_for_side(
                sales_tax_account.kind, JournalEntryConnectorKindChoices.DEBIT
            )
            update_opening_balance(
                sales_tax_account,
                balance_operation_for_action(tax_action),
                total_tax,
                0,
            )
            connector_data.append(
                (
                    sales_tax_account,
                    tax_action,
                    total_tax,
                    sales_tax_account.opening_balance,
                    None,
                )
            )

        if charter_account:
            payment_action = action_for_side(
                charter_account.kind, JournalEntryConnectorKindChoices.CREDIT
            )
            update_opening_balance(
                charter_account,
                balance_operation_for_action(payment_action),
                total_tax,
                0,
            )
            connector_data.append(
                (
                    charter_account,
                    payment_action,
                    total_tax,
                    charter_account.opening_balance,
                    None,
                )
            )

        journal_entry = JournalEntryService.create_journal_entry(
            amount=total_tax,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALES_TAX,
            is_transaction=False,
            is_journal_entry=True,
            company=company,
            object=sales_tax,
        )
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total_tax,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            created_by=user.get_employee(),
        )

        return sales_tax
