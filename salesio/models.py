from autoslug import AutoSlugField

from decimal import Decimal
from datetime import date

from django.db import models

from common.choices import DiscountKind, TaxKindChoices, RefundStatusChoices
from common.django_rest.helpers.json_helpers import email_helpers
from common.models import BaseModelWithUID

from creditnoteio.choices import CreditNoteStatusChoices

from .choices import (
    SalesStatusChoices,
    SaleItemStatusChoices,
    SaleReceptStatusChoices,
    SaleReceptKindChoices,
    SalePaymentReceiveStatusChoices,
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveItemModelStatusChoices,
    SaleSettingPeferredDeliveryMethodChoices,
    SaleSettingInvoicePaymentChoices,
    SalesTaxStatusChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_sale_slug,
    get_sale_item_slug,
    get_sale_payment_receive_slug,
    get_sale_payment_receive_item_slug,
    get_sale_setting_slug,
    get_sale_agency_tax_slug,
)
from .managers import (
    SalesQuerySet,
    SalePaymentReceiveQuerySet,
    SalePaymentReceiveItemQuerySet,
)


class Sale(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_sale_slug, unique=True, db_index=True)
    invoice_id = models.CharField(max_length=50, unique=True)
    date = models.DateField(default=date.today)
    email = models.JSONField(default=email_helpers)
    status = models.CharField(
        max_length=50, choices=SalesStatusChoices, default=SalesStatusChoices.DRAFT
    )
    kind = models.CharField(
        max_length=50,
        choices=SaleReceptKindChoices,
        default=SaleReceptKindChoices.SALE,
    )
    tracking_number = models.CharField(max_length=50, blank=True, null=True)
    reference_number = models.CharField(max_length=50, blank=True, null=True)

    # Price related
    discount_kind = models.CharField(
        max_length=20, choices=DiscountKind.choices, default=DiscountKind.FLAT
    )
    discount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    shipping_fee = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # TODO: here will heve one field among total and total_tax
    total_vat = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    due_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)
    tax_kind = models.CharField(
        choices=TaxKindChoices, default=TaxKindChoices.NO_TAX, max_length=20
    )
    expired_date = models.DateField(blank=True, null=True)

    invoice_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    is_invoice = models.BooleanField(default=False)
    is_estimated = models.BooleanField(default=False)
    is_sale_receipt = models.BooleanField(default=False)

    # FK
    customer = models.ForeignKey("customerio.Customer", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    # Recurring Transactions: links a generated estimate back to the template
    # that produced it (null for manual estimates/invoices/receipts).
    source_template = models.ForeignKey(
        "recurringio.RecurringTemplate",
        on_delete=models.SET_NULL,
        related_name="generated_estimates",
        blank=True,
        null=True,
    )
    warehouse = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.CASCADE, blank=True, null=True
    )
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.SET_NULL, null=True, blank=True
    )
    receivable_charter_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="accounts_receivable_set",
    )
    payable_charter_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="accounts_payable_set",
    )
    # Auto tax field for storing automatic tax calculations
    auto_sales_tax = models.JSONField(null=True, blank=True)
    objects = SalesQuerySet.as_manager()

    def __str__(self):
        return f"UID: {self.uid}, Invoice ID: {self.invoice_id}, Status: {self.status}"

    def apply_sale_payment(self, amount):
        amount = Decimal(amount)
        due_total = Decimal(self.due_total)
        deposit = Decimal(self.deposit)
        if amount <= 0:
            raise ValueError("Payment amount must be positive.")

        applied_amount = min(amount, due_total)
        self.due_total = due_total - applied_amount
        self.deposit = deposit + applied_amount
        self.save()
        return applied_amount

    def unapply_sale_payment(self, amount):
        """Put an applied receipt back on the invoice.

        The mirror of `apply_sale_payment`, which had none -- so deleting a
        customer payment left every invoice it settled still showing as paid,
        with nothing owing and no payment behind it. `Purchase` has carried the
        same pair since Pay Bills needed it (`unapply_purchase_payment`); this
        is that, on the sales side.

        Capped at what was actually received -- `deposit` is the record of that
        -- so an unwind can never invent a receivable larger than the invoice.
        A fully-paid invoice returns to PARTIALLY when only part comes back, and
        the caller decides the rest.
        """
        amount = Decimal(amount)
        if amount <= 0:
            raise ValueError("Unapply amount must be positive.")

        restored = min(amount, Decimal(self.deposit))
        self.due_total = Decimal(self.due_total) + restored
        self.deposit = Decimal(self.deposit) - restored
        # Back to OPEN, which is what an unpaid invoice is here -- there is no
        # PARTIALLY or UNPAID in SalesStatusChoices, and inventing one would be
        # a schema change hiding inside a bug fix. An invoice with something
        # still owing is OPEN whether that is all of it or part.
        if restored and self.status == SalesStatusChoices.PAID:
            self.status = SalesStatusChoices.OPEN
        self.save()
        return restored


class SaleItem(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_sale_item_slug, unique=True, db_index=True)
    section = models.CharField(max_length=100, blank=True, null=True)
    note = models.TextField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=50,
        choices=SaleItemStatusChoices,
        default=SaleItemStatusChoices.DRAFT,
    )
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    sale_price = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # Refund related fields
    refund_quantity = models.PositiveIntegerField(default=0)
    refund_status = models.CharField(
        max_length=50, choices=RefundStatusChoices, blank=True, null=True
    )
    refund_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    is_tax = models.BooleanField(default=False)
    # The tax rates and accounts this line was actually posted with.
    #
    # `tax` points at an AgencyTax whose AgencyTaxSet rows carry the rate and the
    # liability account -- both live, mutable configuration. Nothing recorded
    # what was used at the time, so amending a document re-priced its tax at
    # whatever the rate happens to be today, silently restating a figure that may
    # already sit on a filed return. Posting writes the rates here, and a repost
    # reads them back, so an amendment reproduces the tax as originally filed.
    #
    # Shape: [{"tax_set_id": int, "account_id": int, "rate": "5.050"}, ...].
    # NULL means the line predates this column; the poster falls back to the
    # live configuration and stamps it, so a document self-heals on first repost.
    tax_snapshot = models.JSONField(null=True, blank=True)

    # FK
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    tax = models.ForeignKey(
        "agencyio.AgencyTax",
        # SET_NULL, not CASCADE. A tax rate is reference data; deleting one must
        # not delete the documents that used it. On CASCADE, removing a single
        # AgencyTax deleted every sale line, purchase line and credit-note line
        # that referenced it -- and `JournalEntryConnector.saleitem` is itself
        # CASCADE, so the journal legs went with them. The posted figures live on
        # the connectors, so losing the pointer costs provenance, not money.
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"ID: {self.id},  Total: {self.total}"

    def get_quantity(self):
        return self.quantity - self.refund_quantity

    def get_total(self):
        return self.total - self.refund_total


# class SaleReceipt(BaseModelWithUID):
#     slug = AutoSlugField(
#         populate_from=get_sale_receipt_slug, unique=True, db_index=True
#     )
#     date = models.DateField(default=date.today)
#     reference_number = models.CharField(max_length=50, blank=True, null=True)

#     discount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     shipping_fee = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     total_vat = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     total_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     due_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
#     description = models.TextField(null=True, blank=True)
#     status = models.CharField(
#         max_length=50,
#         choices=SaleReceptStatusChoices,
#         default=SaleReceptStatusChoices.DRAFT,
#     )
#     kind = models.CharField(
#         max_length=50,
#         choices=SaleReceptKindChoices,
#         default=SaleReceptKindChoices.SALE,
#     )
#     cheque_number = models.CharField(max_length=50, blank=True, null=True)

#     # FK
#     customer = models.ForeignKey("customerio.Customer", on_delete=models.CASCADE)
#     created_by = models.ForeignKey(
#         "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
#     )
#     payment_method = models.ForeignKey(
#         "paymentio.PaymentMethod", on_delete=models.SET_NULL, null=True, blank=True
#     )
#     warehouse = models.ForeignKey(
#         "wirehouseio.Warehouse", on_delete=models.CASCADE, blank=True, null=True
#     )
#     deposit_to = models.ForeignKey(
#         "accounts.ChartOfAccount",
#         on_delete=models.CASCADE,
#         blank=True,
#         null=True,
#         related_name="deposit_to_set",
#     )
#     refund_from = models.ForeignKey(
#         "accounts.ChartOfAccount",
#         on_delete=models.CASCADE,
#         blank=True,
#         null=True,
#         related_name="refund_from_set",
#     )

#     def __str__(self):
#         return f"ID: {self.id},  Total: {self.total}"


# class SaleReceiptConnector(BaseModelWithUID):
#     slug = AutoSlugField(
#         populate_from=get_sale_receipt_connector_slug, unique=True, db_index=True
#     )

#     # FK
#     sale_receipt = models.ForeignKey(
#         SaleReceipt, on_delete=models.CASCADE, related_name="connectors"
#     )
#     sale = models.ForeignKey(Sale, on_delete=models.CASCADE)

#     def __str__(self):
#         return f"ID: {self.id}"


class SalePaymentReceive(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_sale_payment_receive_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    email = models.JSONField(default=email_helpers)
    status = models.CharField(
        max_length=50,
        choices=SalePaymentReceiveStatusChoices,
        default=SalePaymentReceiveStatusChoices.DRAFT,
    )
    reference_number = models.CharField(max_length=50, blank=True, null=True)

    # Price related
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    due_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)

    # FK
    customer = models.ForeignKey("customerio.Customer", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.DO_NOTHING
    )
    deposit_to = models.ForeignKey("accounts.ChartOfaccount", on_delete=models.CASCADE)
    objects = SalePaymentReceiveQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Status: {self.status}, Total: {self.total}"


class SalePaymentReceiveItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_sale_payment_receive_item_slug, unique=True, db_index=True
    )
    status = models.CharField(
        choices=SalePaymentReceiveItemModelStatusChoices,
        default=SalePaymentReceiveItemModelStatusChoices.DRAFT,
        max_length=50,
    )
    model_kind = models.CharField(
        choices=SalePaymentReceiveItemModelKindChoices, max_length=50
    )

    # Price related
    # TODO: total will be required
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    used_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # FK
    sale_payment_receive = models.ForeignKey(
        SalePaymentReceive, on_delete=models.CASCADE, blank=True, null=True
    )
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, blank=True, null=True)
    credit_note = models.ForeignKey(
        "creditnoteio.CreditNote", on_delete=models.CASCADE, blank=True, null=True
    )

    objects = SalePaymentReceiveItemQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Status: {self.status}, Model Kind: {self.model_kind}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.credit_note:
            self.update_credit_note_status()

    def update_credit_note_status(self):
        if self.sale_payment_receive.deposit >= self.credit_note.total:
            self.credit_note.status = CreditNoteStatusChoices.CLOSE
            self.credit_note.save()


class SalesTax(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_sale_agency_tax_slug, unique=True, db_index=True
    )
    sales_tax_period = models.CharField(max_length=250, blank=True, null=True)
    sales_tax_due_date = models.DateField(blank=True, null=True)
    total_sales_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    status = models.CharField(
        max_length=50,
        choices=SalesTaxStatusChoices,
        default=SalesTaxStatusChoices.DRAFT,
    )

    # fk
    charter_account = models.ForeignKey(
        "accounts.ChartOfaccount", on_delete=models.CASCADE, blank=True, null=True
    )
    agency = models.ForeignKey(
        "agencyio.Agency", on_delete=models.CASCADE, blank=True, null=True
    )
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, blank=True, null=True
    )
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, Sales Tax Period: {self.sales_tax_period}, Status: {self.status}"


class SaleSetting(BaseModelWithUID):
    """Always keep setting-related models at the bottom for better maintainability.
    Insert any new models above `SaleSetting` as needed to preserve logical structure.
    """

    slug = AutoSlugField(
        populate_from=get_sale_setting_slug, unique=True, db_index=True
    )

    # Sales from content
    preferred_delivery_method = models.CharField(
        max_length=50,
        choices=SaleSettingPeferredDeliveryMethodChoices,
        blank=True,
        null=True,
    )
    is_shipping = models.BooleanField(default=False)
    is_customer_transaction_number = models.BooleanField(default=False)
    is_service_date = models.BooleanField(default=False)
    is_discount = models.BooleanField(default=False)
    is_deposit = models.BooleanField(default=False)
    is_tag = models.BooleanField(default=False)

    # Invoice payments
    invoice_payment = models.CharField(
        max_length=50, choices=SaleSettingInvoicePaymentChoices, blank=True, null=True
    )

    # Product and services
    is_product_and_service = models.BooleanField(default=False)
    is_sku = models.BooleanField(default=False)
    is_quantity_and_price = models.BooleanField(default=False)
    is_available_stock = models.BooleanField(default=False)

    # Reminders
    is_reminder = models.BooleanField(default=False)

    # Statements
    is_show_transactions_as_single_line = models.BooleanField(default=False)
    is_include_transaction_details = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    prefered_term = models.ForeignKey(
        "termio.Term", on_delete=models.SET_NULL, blank=True, null=True
    )
    prefered_payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.SET_NULL, blank=True, null=True
    )

    def __str__(self):
        return (
            f"ID: {self.id}, Preferred delivery method {self.preferred_delivery_method}"
        )
