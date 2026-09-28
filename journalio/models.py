from autoslug import AutoSlugField

from datetime import date

from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    JournalEntryStatusChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_journal_entry_slug,
    get_journal_entry_connector_slug,
)

from .managers import JournalEntryQuerySet


class JournalEntry(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_journal_entry_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    entry_number = models.CharField(max_length=50, blank=True, null=True)
    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    status = models.CharField(
        max_length=50,
        choices=JournalEntryStatusChoices,
        default=JournalEntryStatusChoices.DRAFT,
    )
    kind = models.CharField(
        max_length=50,
        choices=JournalEntryKindChoices,
        default=JournalEntryKindChoices.PURCHASE,
    )
    is_journal_entry = models.BooleanField(default=True)
    is_transaction = models.BooleanField(default=False)
    is_deposit = models.BooleanField(
        default=False
    )  # Indicates the undeposited funds deposit
    description = models.TextField(blank=True, null=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    # purchase related
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.CASCADE, blank=True, null=True
    )
    expense = models.ForeignKey(
        "purchaseio.Expense", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_payment = models.ForeignKey(
        "purchaseio.PurchasePayment", on_delete=models.CASCADE, blank=True, null=True
    )
    pay_bill = models.ForeignKey(
        "purchaseio.PayBill", on_delete=models.CASCADE, blank=True, null=True
    )

    # sale related
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.CASCADE, blank=True, null=True
    )
    sale_payment_receive = models.ForeignKey(
        "salesio.SalePaymentReceive", on_delete=models.CASCADE, blank=True, null=True
    )
    credit_note = models.ForeignKey(
        "creditnoteio.CreditNote", on_delete=models.CASCADE, blank=True, null=True
    )
    stock_adjustment = models.ForeignKey(
        "stockio.StockAdjustment", on_delete=models.CASCADE, blank=True, null=True
    )
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    # bank deposit related
    bank_deposit = models.ForeignKey(
        "transactionio.BankDeposit", on_delete=models.CASCADE, blank=True, null=True
    )
    # Links a forced-close adjustment back to the session that made it, so the
    # entry can be explained without reading the memo.
    bank_reconciliation = models.ForeignKey(
        "transactionio.BankReconciliation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    payroll_salary = models.ForeignKey(
        "payrollio.PayrollSalaryProcess",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )  # for salary process journal entry
    tax_payment = models.ForeignKey(
        "payrollio.TaxCenterPayMethod",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )  # for tax payment journal entry
    sales_tax = models.ForeignKey(
        "salesio.SalesTax",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    objects = JournalEntryQuerySet.as_manager()

    class Meta:
        constraints = [
            # BR-14. One forced-discrepancy entry per reconciliation, enforced
            # by the database rather than by the caller remembering.
            #
            # `bank_reconciliation` is set on exactly one kind of entry: the
            # adjustment a forced close posts to Reconciliation Discrepancies.
            # `JournalEntryService.create_journal_entry` does `get_or_create` on
            # that FK, which is what stops a second one today -- but that is a
            # convention inside one helper, and a session that accumulated two
            # adjustments would have booked the same unexplained difference to
            # the ledger twice.
            #
            # Partial, because the column is NULL on every ordinary entry and a
            # plain unique index would allow only one of those in the table.
            models.UniqueConstraint(
                fields=["bank_reconciliation"],
                condition=models.Q(bank_reconciliation__isnull=False),
                name="one_discrepancy_entry_per_reconciliation",
            ),
        ]

    def __str__(self):
        return (
            f"ID: {self.id}, Entry Number: {self.entry_number}, Model kind: {self.kind}"
        )


class JournalEntryConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_journal_entry_connector_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    debit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    credit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    last_balance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    kind = models.CharField(max_length=50, choices=JournalEntryConnectorKindChoices)
    request_kind = models.CharField(
        max_length=50,
        choices=JournalEntryConnectorRequestKindChoices,
        default=JournalEntryConnectorRequestKindChoices.CREATED,
    )
    description = models.TextField(blank=True, null=True)
    is_customer_or_supplier_transaction = models.BooleanField(default=False)

    # FK
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="child_set",
    )
    journal = models.ForeignKey(JournalEntry, on_delete=models.CASCADE)
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.CASCADE, blank=True, null=True
    )
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.CASCADE, blank=True, null=True
    )
    warehose = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.DO_NOTHING, blank=True, null=True
    )
    # PROTECT, not CASCADE: this row IS the ledger. Under CASCADE, deleting an
    # account silently erased its journal lines -- and because JournalEntry has no
    # FK to the account, the parent entries SURVIVED with their remaining legs, so
    # the books were left holding permanently unbalanced entries that no
    # reconciliation could explain. Deleting a transacted account now raises
    # ProtectedError (surfaced as HTTP 409 by common.django_rest.exception_handler).
    # Note PROTECT raises even when the protecting rows are inside the same cascade,
    # which is deliberate: it also stops a company delete taking the ledger with it.
    account = models.ForeignKey("accounts.ChartOfAccount", on_delete=models.PROTECT)
    tax = models.ForeignKey(
        "agencyio.AgencyTax", on_delete=models.DO_NOTHING, blank=True, null=True
    )
    # The cleared marker, and it lives on the LEG rather than on the entry.
    #
    # An entry has legs on several accounts and only the bank leg clears: a
    # payment debits the bank and credits a receivable, and reconciling it says
    # something about the bank side alone. `JournalEntry.bank_reconciliation`
    # already exists and means something different -- "this entry IS the forced
    # discrepancy adjustment for that session" -- so it cannot carry this.
    #
    # SET_NULL, not CASCADE: undoing a reconciliation must return its lines to
    # unreconciled, never destroy them. Deleting the session is the undo.
    reconciliation = models.ForeignKey(
        "transactionio.BankReconciliation",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_index=True,
        related_name="cleared_lines",
    )
    # The date the line was ticked, kept separately from the session's own
    # dates: a line cleared during a session may be ticked on a different day
    # from the statement date the session is closing against.
    cleared_on = models.DateField(blank=True, null=True)
    # PROTECT, not CASCADE -- the leftover half of P0.2.
    #
    # These record which document line a leg came from. On CASCADE, deleting a
    # line silently deleted its journal rows and left the parent entry with
    # missing legs: permanently unbalanced, with nothing recording why. That is
    # the same failure P0.2 closed on `account` above, on three FKs it listed as
    # "consider" and never got to. It was reachable from `Sale`, `Purchase`,
    # `CreditNote`, `Product`, `ChartOfAccount` and -- until 89375ff0 --
    # `AgencyTax`, whose delete endpoint was not even tenant-scoped.
    #
    # Safe now, and not before: every parent soft-deletes (Sale voids; Purchase,
    # CreditNote, Product, ChartOfAccount and Company set REMOVED), and all three
    # line-delete endpoints reverse their legs before removing the line -- the
    # sale line reposts the document (weapi/.../views/sales.py), the credit-note
    # and purchase lines go through `reverse_item_connectors` (33f27fb8,
    # e29dc67a). Flipping these before that work would have turned every leg
    # those paths missed into a 500 on a working endpoint.
    #
    # `ProtectedError` is already mapped to 409 by the project exception handler,
    # so a path that has not reversed its legs now says so instead of quietly
    # breaking the books.
    saleitem = models.ForeignKey(
        "salesio.SaleItem", on_delete=models.PROTECT, blank=True, null=True
    )
    purchase_item = models.ForeignKey(
        "purchaseio.PurchaseItem", on_delete=models.PROTECT, blank=True, null=True
    )
    # PROTECT, like its three siblings above and for the reason
    # `tests_line_fk_protection` records: a deleted document line must not take
    # its journal legs with it, leaving the entry standing and permanently
    # unbalanced. Safe because the Pay Bills delete paths reverse their legs
    # before removing the line, which is the precondition that test names.
    pay_bill_item = models.ForeignKey(
        "purchaseio.PayBillItem",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )
    credit_note_item = models.ForeignKey(
        "creditnoteio.CreditNoteItem", on_delete=models.PROTECT, blank=True, null=True
    )
    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_by_journal_entry_connector_set",
    )
    employee = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employee_journal_entry_connector_set",
    )  # for salary process journal entry

    class Meta(BaseModelWithUID.Meta):
        # Subclassed, NOT a bare `class Meta`. A bare one would silently drop
        # the inherited `ordering = ("-created_at",)`, which is the default
        # ordering every unordered query on this model relies on -- including
        # the register's sibling prefetch, which overrides it deliberately.
        # Django sets `abstract = False` on an inherited Meta, so this is the
        # documented way to add to one.
        indexes = [
            # The register's balance column is a correlated subquery: for each
            # row, sum every leg of the same account up to and including it, in
            # (date, id). Without this it is a scan of the account's whole
            # history per row -- ten of them for a ten-row page. The same index
            # serves the page itself, which filters `account` and orders by
            # `-date, -id`.
            #
            # `id` is in the index because it is the tie-break: two legs sharing
            # a date have no other stable order, and a running balance without
            # one is undefined.
            models.Index(
                fields=["account", "date", "id"],
                name="jec_account_date_id_idx",
            ),
        ]

    def __str__(self):
        return f"ID: {self.id}, Kind: {self.kind}"

    def get_model_kind(self):
        return self.journal.kind
