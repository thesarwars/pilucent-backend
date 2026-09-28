import random, uuid

from autoslug import AutoSlugField

from datetime import date
from decimal import Decimal
from django.db import models

from common.choices import DiscountKind
from common.django_rest.helpers.json_helpers import email_helpers
from common.models import BaseModelWithUID

from creditnoteio.choices import CreditNoteStatusChoices

from .choices import (
    PurchaseStatus,
    PurchaseItemkind,
    PurchaseItemStatus,
    PurchaseTaxKindChoices,
    ExpenseStatusChoices,
    PurchasePaymentStatusChoices,
    PurchasePaymentItemStatusChoices,
    PurchasePaymentItemModelKindChoices,
    PayBillStatusChoices,
    PayBillItemStatusChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_purchase_item_slug,
    get_purchase_slug,
    get_expense_slug,
    get_expense_connector_slug,
    get_purchase_payment_slug,
    get_purchase_payment_item_slug,
    get_purchase_setting_slug,
    get_pay_bill_slug,
    get_pay_bill_item_slug,
)

from .managers import PurchasePaymentItemStatusQuerySet, PurchasePaymentStatusQuerySet


class Purchase(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_purchase_slug, unique=True, db_index=True)
    purchase_id = models.CharField(
        max_length=50, blank=True, null=True, unique=True, default=uuid.uuid4
    )
    date = models.DateField(default=date.today)
    email = models.JSONField(default=email_helpers)
    status = models.CharField(
        max_length=50, choices=PurchaseStatus, default=PurchaseStatus.DRAFT
    )
    tracking_number = models.CharField(
        max_length=50, blank=True, null=True, unique=True, default=uuid.uuid4
    )

    # Price related
    discount_kind = models.CharField(
        max_length=20, choices=DiscountKind.choices, default=DiscountKind.FLAT
    )
    discount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    shipping_fee = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_vat = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    due_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)
    tax_kind = models.CharField(
        choices=PurchaseTaxKindChoices,
        default=PurchaseTaxKindChoices.NO_TAX,
        max_length=20,
    )

    # Expense related
    is_via_expense = models.BooleanField(default=False)

    # Bill related fields
    bill_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    is_bill = models.BooleanField(default=False)

    # Cheque related fields
    is_cheque = models.BooleanField(default=False)
    cheque_number = models.CharField(blank=True, null=True, max_length=100)

    # FK
    supplier = models.ForeignKey("supplierio.Supplier", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    warehouse = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.CASCADE, blank=True, null=True
    )
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.DO_NOTHING, null=True, blank=True
    )
    charter_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE, blank=True, null=True
    )
    # Recurring Transactions: links a generated bill back to the template that
    # produced it (null for manual bills). The occurrence -> bill link lives on
    # recurringio.RecurringOccurrence.generated_purchase.
    source_template = models.ForeignKey(
        "recurringio.RecurringTemplate",
        on_delete=models.SET_NULL,
        related_name="generated_bills",
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"ID: {self.id}, Product: {self.status}"

    def save(self, *args, **kwargs):
        if self.pk is None:
            super().save(*args, **kwargs)
            self.purchase_id = f"#PUR-{self.company.id}{str(self.company.uid).split('-')[2]}{self.id}{str(random.randint(0, 999)).zfill(3)}"
            self.tracking_number = f"#PURTRAC-{self.company.id}{str(self.company.uid).split('-')[2]}{self.id}{str(random.randint(0, 999)).zfill(3)}"
            super().save(update_fields=["purchase_id", "tracking_number"])
        else:
            super().save(*args, **kwargs)

    def get_currency(self):
        return self.currencyconnector_set.first().currency

    def apply_purchase_payment(self, amount):
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

    def unapply_purchase_payment(self, amount):
        """Put an applied payment back on the bill.

        The mirror of `apply_purchase_payment`, and it exists because settling a
        bill has to be undoable: a Pay Bills payment can be amended, its payee
        line deleted, or the whole payment removed, and each of those has to
        leave the bill owing again exactly what it owed.

        Capped at what was actually paid down -- `deposit` is the record of
        that -- so an unwind can never invent a debt larger than the bill.
        """
        amount = Decimal(amount)
        if amount <= 0:
            raise ValueError("Unapply amount must be positive.")

        restored = min(amount, Decimal(self.deposit))
        self.due_total = Decimal(self.due_total) + restored
        self.deposit = Decimal(self.deposit) - restored
        if restored and self.status == PurchaseStatus.COMPLETED:
            self.status = PurchaseStatus.OPEN
        self.save()
        return restored

    def get_address(self, is_shipping):
        address = self.addressconnector_set.filter(
            address__is_shipping=is_shipping
        ).first()
        return address.address if address else None

    def get_billing_address(self):
        return self.get_address(is_shipping=False)

    def get_shipping_address(self):
        return self.get_address(is_shipping=True)


class PurchaseItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_purchase_item_slug, unique=True, db_index=True
    )
    section = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=50, choices=PurchaseItemStatus, default=PurchaseItemStatus.DRAFT
    )
    kind = models.CharField(
        max_length=50, choices=PurchaseItemkind, default=PurchaseItemkind.PRODUCT
    )
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    purchase_price = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)
    opening_quantity = models.IntegerField(default=0)
    quantity = models.PositiveIntegerField(default=0)
    note = models.TextField(max_length=100, blank=True, null=True)

    # FK
    purchase = models.ForeignKey("Purchase", on_delete=models.CASCADE)
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    tax = models.ForeignKey(
        "agencyio.AgencyTax",
        # See SaleItem.tax: CASCADE here let one tax deletion take the lines and
        # their journal legs with it.
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    charter_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id},  Total: {self.total}"


class Expense(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_expense_slug, unique=True, db_index=True)
    expense_id = models.CharField(max_length=20, blank=True, null=True)
    date = models.DateField(default=date.today)
    reference_number = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(
        max_length=50, choices=ExpenseStatusChoices, default=ExpenseStatusChoices.DRAFT
    )

    discount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    shipping_fee = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_vat = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    due_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)

    # FK
    supplier = models.ForeignKey("supplierio.Supplier", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.DO_NOTHING, null=True, blank=True
    )
    payment_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE
    )

    def __str__(self):
        return f"ID: {self.id}"


class ExpenseConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_expense_connector_slug, unique=True, db_index=True
    )

    # FK
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}"


class PurchasePayment(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_purchase_payment_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    email = models.JSONField(default=email_helpers)
    status = models.CharField(
        max_length=50,
        choices=PurchasePaymentStatusChoices,
        default=PurchasePaymentStatusChoices.DRAFT,
    )

    bill_number = models.CharField(max_length=50, blank=True, null=True)

    # Price related
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    due_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(null=True, blank=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    supplier = models.ForeignKey("supplierio.Supplier", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    # TODO : "payment method should have and blank, null respectively will be false"
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.DO_NOTHING, null=True, blank=True
    )
    payment_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE
    )
    objects = PurchasePaymentStatusQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}"


class PurchasePaymentItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_purchase_payment_item_slug, unique=True, db_index=True
    )
    status = models.CharField(
        choices=PurchasePaymentItemStatusChoices,
        default=PurchasePaymentItemStatusChoices.DRAFT,
        max_length=50,
    )
    model_kind = models.CharField(
        choices=PurchasePaymentItemModelKindChoices,
        max_length=50,
        default=PurchasePaymentItemModelKindChoices.PURCHASE,
    )
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    used_total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # FK
    purchase_payment = models.ForeignKey(
        PurchasePayment, on_delete=models.CASCADE, blank=True, null=True
    )
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, blank=True, null=True
    )
    credit_note = models.ForeignKey(
        "creditnoteio.CreditNote", on_delete=models.CASCADE, blank=True, null=True
    )

    objects = PurchasePaymentItemStatusQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.credit_note:
            self.update_credit_note_status()

    def update_credit_note_status(self):
        if self.purchase_payment.deposit >= self.credit_note.total:
            self.credit_note.status = CreditNoteStatusChoices.CLOSE
            self.credit_note.save()


class PayBill(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_pay_bill_slug, unique=True, db_index=True)
    date = models.DateField(default=date.today)
    email = models.JSONField(default=email_helpers)
    status = models.CharField(
        max_length=50,
        choices=PayBillStatusChoices,
        default=PayBillStatusChoices.DRAFT,
    )
    tax_kind = models.CharField(
        choices=PurchaseTaxKindChoices,
        default=PurchaseTaxKindChoices.NO_TAX,
        max_length=20,
    )
    tracking_number = models.CharField(max_length=50, blank=True, null=True)

    # Price related
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    description = models.TextField(blank=True, null=True)

    # FK
    payment_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}"


class PayBillItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_pay_bill_item_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=PayBillItemStatusChoices,
        default=PayBillItemStatusChoices.DRAFT,
    )

    applied_credit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # FK
    supplier = models.ForeignKey("supplierio.Supplier", on_delete=models.CASCADE)
    pay_bill = models.ForeignKey(PayBill, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}"


class PayBillApplication(BaseModelWithUID):
    """Which bills one Pay Bills payee line actually paid, and by how much.

    `PayBillItem` recorded "paid this vendor this much" and named no bill --
    there was no FK to a `Purchase` anywhere in the model. So Pay Bills relieved
    the A/P control account and the vendor balance while every bill it paid sat
    at full value forever: the balance sheet fell, the ageing report did not, and
    the two never reconciled again. `SUPPLIER_GAPS.md` D6.

    A payment is a many-to-many against bills -- one payment can clear several,
    one bill can take several payments -- so the allocation is its own row rather
    than a column on either side. Keeping it explicit is also what makes the
    unwind exact: amending or deleting a payee line restores precisely the bills
    it touched, by the amounts it touched them for, rather than guessing from a
    total.
    """

    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    pay_bill_item = models.ForeignKey(
        PayBillItem, on_delete=models.CASCADE, related_name="applications"
    )
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="pay_bill_applications"
    )

    class Meta:
        indexes = [
            models.Index(fields=["purchase"]),
            models.Index(fields=["pay_bill_item"]),
        ]

    def __str__(self):
        return f"ID: {self.id}, Amount: {self.amount}"


class PurchaseSetting(BaseModelWithUID):
    """Always keep setting-related models at the bottom for better maintainability.
    Insert any new models above `PurchaseSetting` as needed to preserve logical structure.
    """

    slug = AutoSlugField(
        populate_from=get_purchase_setting_slug, unique=True, db_index=True
    )

    # Bill and expenses
    is_purchase_item = models.BooleanField(default=False)
    is_tag = models.BooleanField(default=False)
    is_track_expense_and_items_by_customer = models.BooleanField(default=False)
    is_expense_and_item_billable = models.BooleanField(default=False)
    is_purchase_order = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}, Company: {self.company.title}"
