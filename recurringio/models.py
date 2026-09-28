"""Recurring Transactions data model (Phase 1: Bill).

Parent/child model: a ``RecurringTemplate`` is a reusable blueprint (never a
ledger transaction) that produces real bills over time. Lines live on
``RecurringTemplateLine``; each produced bill/reminder is logged as a
``RecurringOccurrence`` (its ``unique(template, occurrence_date)`` is the
generation idempotency key). See
``docs/updated-prompts/Balanzify_Recurring_Transactions_Bill.md`` (section 12).

Every table carries ``company`` so the same RLS tenant policy used on the core
tables applies (see ``common/db/rls.py``).
"""

from django.db import models

from common.models import BaseModelWithUID

from common.choices import DiscountKind

from .choices import (
    RecurringAcceptanceStatusChoices,
    RecurringDayModeChoices,
    RecurringEndTypeChoices,
    RecurringFrequencyChoices,
    RecurringLineTypeChoices,
    RecurringOccurrenceStatusChoices,
    RecurringOrdinalChoices,
    RecurringTemplateStatusChoices,
    RecurringTemplateTypeChoices,
    RecurringTxnTypeChoices,
    RecurringWhenToChargeChoices,
)


class RecurringTemplate(BaseModelWithUID):
    # ``title`` (from BaseModelWithUID) is unused; ``name`` is the template label.
    name = models.CharField(max_length=100)
    txn_type = models.CharField(
        max_length=20,
        choices=RecurringTxnTypeChoices.choices,
        default=RecurringTxnTypeChoices.BILL,
    )
    template_type = models.CharField(
        max_length=20,
        choices=RecurringTemplateTypeChoices.choices,
        default=RecurringTemplateTypeChoices.SCHEDULED,
    )
    status = models.CharField(
        max_length=20,
        choices=RecurringTemplateStatusChoices.choices,
        default=RecurringTemplateStatusChoices.ACTIVE,
    )

    # Bill header
    mailing_address = models.TextField(blank=True, null=True)
    memo = models.TextField(blank=True, null=True)
    autopay_enabled = models.BooleanField(default=False)
    currency_code = models.CharField(max_length=3, default="USD")

    # The account money is paid from. For EXPENSE it is the bank/credit-card
    # account (credit side of a direct expense); for CHEQUE it is the bank (cash)
    # account the cheque is drawn on. Required for EXPENSE and CHEQUE, unused for
    # BILL.
    payment_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.SET_NULL,
        related_name="recurring_payment_templates",
        blank=True,
        null=True,
    )
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.SET_NULL, blank=True, null=True
    )

    # Cheque-only settings (txn_type=CHEQUE). A cheque is a numbered instrument
    # drawn on the bank account above; when print_later is set the number is
    # assigned at print time, so cheque_number may be blank or a label ("EFT").
    cheque_number = models.CharField(max_length=50, blank=True, null=True)
    print_later = models.BooleanField(default=False)
    permit_number = models.CharField(max_length=100, blank=True, null=True)

    # Estimate-only settings (txn_type=ESTIMATE). An estimate is a non-posting
    # sales quote addressed to a customer (see ``customer`` below); these carry
    # the email recipients and customer-facing message. Unused for money-out
    # types. ``mailing_address`` doubles as the estimate billing address.
    email_to = models.TextField(blank=True, null=True)  # comma-separated
    email_cc = models.TextField(blank=True, null=True)
    email_bcc = models.TextField(blank=True, null=True)
    auto_email = models.BooleanField(default=False)
    # Customer-facing message. For ESTIMATE this is "message on estimate"; for
    # REFUND_RECEIPT the frontend calls it "message on receipt" (same field).
    message_on_estimate = models.TextField(blank=True, null=True)

    # Hidden internal note (PAYMENT). Customer-facing text lives in `memo`.
    internal_note = models.TextField(blank=True, null=True)

    # PAYMENT only: whether the template charges on its schedule or waits for
    # the customer to accept. ACCEPT generates nothing until an acceptance
    # exists — see RecurringWhenToChargeChoices.
    when_to_charge = models.CharField(
        max_length=20,
        choices=RecurringWhenToChargeChoices.choices,
        default=RecurringWhenToChargeChoices.FUTURE,
    )
    acceptance_status = models.CharField(
        max_length=20,
        choices=RecurringAcceptanceStatusChoices.choices,
        blank=True,
        null=True,
    )

    # INVOICE document-level money inputs. Unlike totals these are NOT
    # derivable from lines — a user typed them — so dropping them would
    # silently generate undiscounted invoices. `discount` is always an
    # absolute money amount, never a percent: the client converts a typed
    # percentage into money before storing, and `discount_kind` only records
    # how the user typed it. `deposit` requires a settlement account
    # (payment_account, wire name deposit_to) to book against.
    discount_kind = models.CharField(
        max_length=20, choices=DiscountKind.choices, default=DiscountKind.PERCENTAGE
    )
    discount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    shipping_fee = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    deposit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # INVOICE only. `payment_instructions` has no counterpart on we/sales, so
    # it is template-only metadata for now; `include_unbilled_charges` is
    # persisted but a NO-OP at fire time in v1 (nothing in the product queries
    # a customer's open billable charges yet).
    payment_instructions = models.TextField(blank=True, null=True)
    include_unbilled_charges = models.BooleanField(default=False)

    # DEPOSIT only. Cash back is money taken back out of the deposit, so it is
    # SUBTRACTED from the total -- the only type where an extra amount reduces
    # it. `track_returns` maps to no field on any real transaction: it is
    # persisted as a flag with no fire-time behaviour in v1.
    cash_back_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.SET_NULL,
        related_name="recurring_cash_back_templates",
        blank=True,
        null=True,
    )
    cash_back_memo = models.CharField(max_length=255, blank=True, null=True)
    cash_back_amount = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    track_returns = models.BooleanField(default=False)

    # SALES_RECEIPT only: a ship-FROM origin, prefilled from the company's own
    # address. No live sales endpoint has a counterpart, so this is template
    # metadata that never reaches a generated receipt. Not to be confused with
    # full_shipping_address below, which is a ship-TO address.
    shipping_from = models.TextField(blank=True, null=True)

    # PURCHASE_ORDER shipping block. `ship_to` is a CUSTOMER (goods can be
    # drop-shipped to one) and is template-only metadata: we/purchases stores
    # only the flattened address, not a ship-to party. `shipping_by` is free
    # text deliberately -- the recurring screen uses an input where the real PO
    # screen uses carrier chips, so an enum here would reject valid input.
    ship_to = models.ForeignKey(
        "customerio.Customer",
        on_delete=models.SET_NULL,
        related_name="recurring_ship_to_templates",
        blank=True,
        null=True,
    )
    full_shipping_address = models.TextField(blank=True, null=True)
    shipping_by = models.CharField(max_length=100, blank=True, null=True)

    # ESTIMATE only: how long each generated quote stays valid, in days after
    # its occurrence date. Stored as a duration rather than an absolute date
    # because a fixed expiry is meaningless on a template that fires for years.
    # Null leaves the generated estimate open-ended.
    expiry_days = models.PositiveIntegerField(blank=True, null=True)

    # Sales-document settlement fields (txn_type=REFUND_RECEIPT). The account the
    # refund leaves is ``payment_account`` (reused). ``reference_number`` is the
    # cheque number and ``tracking_number`` the refund-receipt number on the live
    # refund screen; ``statement_memo`` is the customer statement note.
    reference_number = models.CharField(max_length=50, blank=True, null=True)
    tracking_number = models.CharField(max_length=50, blank=True, null=True)
    statement_memo = models.TextField(blank=True, null=True)
    # Document-level tax: the kind (exclusive/inclusive/no-tax) and the rate that
    # is also stamped onto every taxed line.
    tax_kind = models.CharField(max_length=20, blank=True, null=True)
    tax = models.ForeignKey(
        "agencyio.AgencyTax",
        on_delete=models.SET_NULL,
        related_name="recurring_document_templates",
        blank=True,
        null=True,
    )

    # Behaviour offsets (one applies depending on template_type)
    create_days_in_advance = models.PositiveIntegerField(blank=True, null=True)
    remind_days_before = models.PositiveIntegerField(blank=True, null=True)

    # Cached total (sum of lines + tax), recomputed on save.
    total_amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # Schedule (embedded value object; null for Unscheduled templates)
    frequency = models.CharField(
        max_length=20, choices=RecurringFrequencyChoices.choices, blank=True, null=True
    )
    interval_count = models.PositiveIntegerField(default=1)
    day_mode = models.CharField(
        max_length=20, choices=RecurringDayModeChoices.choices, blank=True, null=True
    )
    day_of_month = models.PositiveIntegerField(blank=True, null=True)  # 1-31
    weekday = models.PositiveIntegerField(blank=True, null=True)  # 0=Mon .. 6=Sun
    ordinal = models.CharField(
        max_length=10, choices=RecurringOrdinalChoices.choices, blank=True, null=True
    )
    month_of_year = models.PositiveIntegerField(blank=True, null=True)  # 1-12 (yearly)
    start_date = models.DateField(blank=True, null=True)
    end_type = models.CharField(
        max_length=20,
        choices=RecurringEndTypeChoices.choices,
        default=RecurringEndTypeChoices.NONE,
    )
    end_date = models.DateField(blank=True, null=True)
    end_after_occurrences = models.PositiveIntegerField(blank=True, null=True)

    # Run state
    previous_run_date = models.DateField(blank=True, null=True)
    next_run_date = models.DateField(blank=True, null=True)
    occurrences_generated = models.PositiveIntegerField(default=0)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    supplier = models.ForeignKey(  # payee/vendor (money-out types)
        "supplierio.Supplier", on_delete=models.SET_NULL, blank=True, null=True
    )
    customer = models.ForeignKey(  # quote recipient (ESTIMATE only)
        "customerio.Customer",
        on_delete=models.SET_NULL,
        related_name="recurring_templates",
        blank=True,
        null=True,
    )
    terms = models.ForeignKey(
        "termio.Term", on_delete=models.SET_NULL, blank=True, null=True
    )
    warehouse = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.SET_NULL, blank=True, null=True
    )
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Name: {self.name}, Type: {self.template_type}"


class RecurringTemplateLine(BaseModelWithUID):
    line_type = models.CharField(
        max_length=20, choices=RecurringLineTypeChoices.choices
    )
    position = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True, null=True)
    quantity = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=4, blank=True, null=True
    )
    rate = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=4, blank=True, null=True
    )
    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    is_billable = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    template = models.ForeignKey(
        RecurringTemplate, related_name="lines", on_delete=models.CASCADE
    )
    charter_account = models.ForeignKey(  # category (account-based) lines
        "accounts.ChartOfAccount", on_delete=models.SET_NULL, blank=True, null=True
    )
    product = models.ForeignKey(  # item (product/service) lines
        "productio.Product", on_delete=models.SET_NULL, blank=True, null=True
    )
    tax = models.ForeignKey(
        "agencyio.AgencyTax", on_delete=models.SET_NULL, blank=True, null=True
    )
    # DEPOSIT fund rows carry their own payer and instrument -- a deposit has
    # no document-level party, unlike every other type. `customer` and
    # `supplier` are mutually exclusive; both are null when no payer is picked.
    supplier = models.ForeignKey(
        "supplierio.Supplier",
        on_delete=models.SET_NULL,
        related_name="recurring_template_lines",
        blank=True,
        null=True,
    )
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.SET_NULL, blank=True, null=True
    )
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.SET_NULL, blank=True, null=True
    )

    class Meta:
        ordering = ("position", "created_at")

    def __str__(self):
        return f"ID: {self.id}, {self.line_type}, Amount: {self.amount}"


class RecurringOccurrence(BaseModelWithUID):
    occurrence_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=RecurringOccurrenceStatusChoices.choices
    )
    reminded_at = models.DateTimeField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    error_detail = models.TextField(blank=True, null=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    template = models.ForeignKey(
        RecurringTemplate, related_name="occurrences", on_delete=models.CASCADE
    )
    # What this firing produced. Purchase-side types (bill / expense / cheque)
    # land in ``generated_purchase``; sales-side ones (estimate, and the invoice
    # / sales-receipt / credit-memo types to come) produce a Sale instead, so
    # both links are needed to make the run history complete.
    generated_purchase = models.ForeignKey(
        "purchaseio.Purchase",
        on_delete=models.SET_NULL,
        related_name="recurring_occurrences",
        blank=True,
        null=True,
    )
    generated_sale = models.ForeignKey(
        "salesio.Sale",
        on_delete=models.SET_NULL,
        related_name="recurring_occurrences",
        blank=True,
        null=True,
    )
    generated_credit_note = models.ForeignKey(
        "creditnoteio.CreditNote",
        on_delete=models.SET_NULL,
        related_name="recurring_occurrences",
        blank=True,
        null=True,
    )
    # A DEPOSIT produces neither a Purchase nor a Sale.
    generated_deposit = models.ForeignKey(
        "transactionio.BankDeposit",
        on_delete=models.SET_NULL,
        related_name="recurring_occurrences",
        blank=True,
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["template", "occurrence_date"],
                name="unique_recurring_occurrence_per_template_date",
            )
        ]

    def __str__(self):
        return f"ID: {self.id}, {self.template_id} @ {self.occurrence_date}"
