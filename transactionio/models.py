from autoslug import AutoSlugField
from datetime import date
from django.db import models
from common.models import BaseModelWithUID

from .managers import TransactionQuerySet
from .django_rest.helpers.slug_helpers import (
    get_transaction_information_slug,
    get_transaction_method_slug,
    trx_rule_slug,
    rule_params_slug,
    rule_assign_slug,
    get_bank_deposit_slug,
    get_bank_deposit_item_slug,
    get_bank_reconcile_slug,
)
from .choices import (
    BankReconciliationStatusChoices,
    TransactionStatusChoices,
    TrxRuleTypeChoices,
    ParamsFieldChoices,
    ParamsOperationsChoices,
    TrxAssignTypeChoices,
    BankDepositStatusChoices,
    DepositItemTypeChoices,
    DepositItemPaymentMethodChoices,
)


class TransactionMethod(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_transaction_method_slug, unique=True, db_index=True
    )
    status = models.CharField(max_length=50, default="DRAFT")
    company = models.ForeignKey("companyio.Company", models.CASCADE)
    # created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ID: {self.uid}, Company: {self.company.name}"


class TransactionInformation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_transaction_information_slug, unique=True, db_index=True
    )
    date = models.DateField()
    description = models.TextField()
    # A statement line is money in or money out, and the constraints below say
    # so. These were independent, unvalidated and unconstrained: a row could
    # carry both, or carry a negative, and whatever was there got summed.
    #
    # `(19, 2)` and not `(10, 2)` -- BR-30. Every figure these feed carries 19
    # digits: `beginning_balance` and `statement_ending_balance` below, and the
    # ledger's own `debit`/`credit`. The same computation was being carried at
    # two precisions, and the narrower end capped silently at 99,999,999.99.
    received = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )
    spent = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    chart_of_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True
    )
    category = models.CharField(max_length=255, null=True, blank=True)
    payee = models.CharField(max_length=255, null=True, blank=True)
    is_spam = models.BooleanField(default=False)
    is_matched = models.BooleanField(default=False)
    transaction_status = models.CharField(
        max_length=11,
        choices=TransactionStatusChoices,
        default=TransactionStatusChoices.FOR_REVIEW,
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    check_number = models.CharField(max_length=255, null=True, blank=True)
    journal_entry = models.ForeignKey(
        "journalio.JournalEntry", on_delete=models.SET_NULL, null=True, blank=True
    )
    matched_rule = models.ForeignKey(
        "transactionio.TransactionRules",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matched_transactions",
    )

    objects = TransactionQuerySet.as_manager()

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["company", "date", "description"]),
        ]
        constraints = [
            # BR-18. Neither side may be negative. A refund is a receipt and a
            # reversal is a payment; a negative in either column is a sign error
            # in the import, and it used to sum straight into the cleared total.
            #
            # NULL-safe by construction: `NULL >= 0` is NULL, and a CHECK passes
            # on NULL. An unparsed column stays unparsed rather than becoming a
            # zero that looks deliberate.
            models.CheckConstraint(
                condition=models.Q(received__gte=0) | models.Q(received__isnull=True),
                name="statement_line_received_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(spent__gte=0) | models.Q(spent__isnull=True),
                name="statement_line_spent_not_negative",
            ),
            # And not both at once. A line that is simultaneously a receipt and
            # a payment has no meaning on a bank statement, and it moved the
            # reconciliation by the difference between two numbers that were
            # never meant to be netted.
            models.CheckConstraint(
                condition=~(models.Q(received__gt=0) & models.Q(spent__gt=0)),
                name="statement_line_is_receipt_or_payment_not_both",
            ),
        ]

    def __str__(self):
        return f"{self.date} - {self.description[:50]}"


class TransactionRules(BaseModelWithUID):
    slug = AutoSlugField(populate_from=trx_rule_slug, unique=True, db_index=True)
    transaction_type = models.CharField(max_length=255, choices=TrxRuleTypeChoices)
    all_account = models.BooleanField(default=False)
    bank_accounts = models.ManyToManyField("accounts.ChartOfAccount", blank=True)
    is_all = models.BooleanField(default=False)
    auto_add = models.BooleanField(default=False)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    is_excluded = models.BooleanField(default=False)

    def applies_to_account(self, account):
        """
        Check if the rule applies to a specific account.
        """
        return self.all_account or self.bank_accounts.filter(uid=account.uid).exists()

    def __str__(self):
        return f"{self.uid}, title: {self.title}"


class TransactionRuleParams(BaseModelWithUID):
    slug = AutoSlugField(populate_from=rule_params_slug, unique=True, db_index=True)
    rule = models.ForeignKey(
        TransactionRules, on_delete=models.CASCADE, related_name="params"
    )
    field = models.CharField(
        max_length=255,
        choices=ParamsFieldChoices,
        default=ParamsFieldChoices.DESCRIPTION,
    )
    operation = models.CharField(
        max_length=255,
        choices=ParamsOperationsChoices,
        default=ParamsOperationsChoices.CONTAINS,
    )
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.rule.slug} - {self.field}: {self.value}"


class TransactionRuleAssign(BaseModelWithUID):
    slug = AutoSlugField(populate_from=rule_assign_slug, unique=True, db_index=True)
    trx_type = models.CharField(
        max_length=255,
        choices=TrxAssignTypeChoices,
        default=TrxAssignTypeChoices.DEPOSIT,
    )
    rule = models.OneToOneField(
        TransactionRules, on_delete=models.CASCADE, related_name="assign"
    )
    chart_of_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True
    )
    payee = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.SET_NULL, null=True, blank=True
    )
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.SET_NULL, null=True, blank=True
    )
    memo = models.CharField(max_length=255, blank=True, null=True)
    is_split = models.BooleanField(default=False)


class BankDeposit(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_bank_deposit_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    description = models.TextField(blank=True, null=True)
    bank_chart_of_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE, blank=True, null=True
    )
    cash_back_memo = models.CharField(max_length=255, blank=True, null=True)
    cash_back_amount = models.DecimalField(
        max_digits=19, decimal_places=3, default=0.00
    )
    cash_back_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="cash_back_account",
    )
    status = models.CharField(
        max_length=50,
        choices=BankDepositStatusChoices,
        default=BankDepositStatusChoices.DRAFT,
    )
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"Bank Deposit {self.date} - {self.bank_chart_of_account.title if self.bank_chart_of_account else 'No Account'}"

    @property
    def total_deposit_amount(self):
        """Calculate total amount of all deposit items"""
        return self.deposit_items.aggregate(total=models.Sum("amount"))["total"] or 0.00

    @property
    def net_deposit_amount(self):
        """Calculate net deposit amount after cash back"""
        return self.total_deposit_amount - self.cash_back_amount


class BankDepositItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_bank_deposit_item_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    description = models.TextField(blank=True, null=True)
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    type = models.CharField(
        max_length=50,
        choices=DepositItemTypeChoices,
        default=DepositItemTypeChoices.PAYMENT,
    )
    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    bank_deposit = models.ForeignKey(
        BankDeposit, on_delete=models.CASCADE, related_name="deposit_items"
    )
    received_from_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.SET_NULL, blank=True, null=True
    )
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.SET_NULL, blank=True, null=True
    )
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.SET_NULL, blank=True, null=True
    )
    payment_method = models.ForeignKey(
        "paymentio.PaymentMethod", on_delete=models.DO_NOTHING, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id},  Amount: {self.amount}"
    

class BankReconciliation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_bank_reconcile_slug, unique=True, db_index=True
    )
    # Both required. A reconciliation without an account or a company is not a
    # partially-filled record, it is a row nothing can interpret -- and
    # `__str__` dereferenced `bank_account.title` unguarded, so one would crash
    # the admin changelist. Safe to tighten: 0 rows exist after the 2026-08-25
    # cleanup, so there is nothing to backfill.
    #
    # `on_delete` stays CASCADE rather than becoming PROTECT. PROTECT fires even
    # when the protecting rows are inside the same cascade, so it would re-break
    # the admin company delete that `15c78456` fixed. The ledger legs are what
    # must survive an account delete, and `JournalEntryConnector.account` is
    # already PROTECT for exactly that.
    bank_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        related_name="reconciliations",
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    beginning_balance = models.DecimalField(max_digits=19, decimal_places=2)
    statement_ending_balance = models.DecimalField(max_digits=19, decimal_places=2)
    statement_ending_date = models.DateField()

    # The session's place in its lifecycle. Replaces an `is_closed` boolean,
    # which could not survive undo: `is_closed=True` beside an `is_undone=True`
    # means *not closed*, and every reader that forgot the second flag would be
    # wrong silently. Spec s21 names these states directly.
    status = models.CharField(
        max_length=20,
        choices=BankReconciliationStatusChoices,
        default=BankReconciliationStatusChoices.OPEN,
        db_index=True,
    )
    reconciled_on = models.DateField(null=True, blank=True)

    # A session may only close at a difference of zero. Closing anyway is a
    # deliberate, recorded exception -- spec BLZ-FIN-REG-SPEC-001 s16.6 -- so it
    # carries the amount that could not be explained, why, and the entry that
    # put it on the books. Without these three a forced close is
    # indistinguishable from a clean one after the fact.
    # BR-28. Who closed it, kept apart from `created_by`: opening a session and
    # signing it off are different acts, and segregation of duties (spec s13)
    # turns on being able to tell them apart. Nullable because an open session
    # has not been closed by anyone.
    closed_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliations_closed",
    )

    # BR-35. The report as it stood when the session closed.
    #
    # A reconciliation report cannot be recomputed after the fact, and that is
    # arithmetic rather than a storage preference: the ledger keeps moving. An
    # amend appends a delta leg to a document this session already cleared, a
    # void appends a reversal, and both change what the candidate query returns
    # for a period that is already closed. Re-running the report next month
    # would give a different answer from the one the bank agreed to, with
    # nothing recording that it changed.
    #
    # JSON rather than rows, because this is evidence and not data. Nothing
    # should join to it, aggregate it, or keep it in step with the ledger.
    report_snapshot = models.JSONField(null=True, blank=True)

    # Undo (spec s16.7). A closed session unwinds, its lines revert to cleared,
    # and the reason joins the record. Kept beside `reconciled_on` and
    # `closed_by` rather than replacing them: an undone session should still say
    # when it closed and who closed it, or the audit trail loses the act being
    # undone.
    undone_on = models.DateField(null=True, blank=True)
    undone_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliations_undone",
    )
    undo_reason = models.TextField(blank=True, null=True)

    is_forced = models.BooleanField(default=False)
    forced_reason = models.TextField(blank=True, null=True)
    forced_difference = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )

    class Meta:
        constraints = [
            # BR-15. One reconciliation per account per statement period.
            # Nothing stopped two sessions being opened on the same account and
            # the same statement date, each ticking a different half of the
            # same activity and each closing at a difference of zero.
            # One LIVE reconciliation per account per statement period.
            #
            # Partial, on purpose. An undone session keeps its row -- it is the
            # only durable audit surface, since this model is not registered
            # with auditlog -- but it must not hold the period hostage, or undo
            # would make a period permanently unreconcilable, which is the
            # opposite of what undo is for.
            models.UniqueConstraint(
                fields=["company", "bank_account", "statement_ending_date"],
                condition=models.Q(
                    status__in=[
                        BankReconciliationStatusChoices.OPEN,
                        BankReconciliationStatusChoices.CLOSED,
                    ]
                ),
                name="unique_live_reconciliation_per_account_period",
            ),
            # A closed session carries the date it closed, and an open one does
            # not. These two fields were set together in one place and nothing
            # else enforced the pairing, so a row could read closed with no
            # date -- indistinguishable from a session someone closed by hand.
            # An open session has no close date; a closed or undone one does.
            # UNDONE keeps `reconciled_on` because it records when the session
            # closed, which undo does not erase -- it is the act being undone.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=BankReconciliationStatusChoices.OPEN,
                        reconciled_on__isnull=True,
                    )
                    | models.Q(
                        status__in=[
                            BankReconciliationStatusChoices.CLOSED,
                            BankReconciliationStatusChoices.UNDONE,
                        ],
                        reconciled_on__isnull=False,
                    )
                ),
                name="reconciliation_closed_iff_reconciled_on",
            ),
            # A forced close carries its reason and the amount it could not
            # explain. Without all three a forced close is indistinguishable
            # from a clean one after the fact, which is the whole point of
            # recording it.
            models.CheckConstraint(
                condition=(
                    models.Q(is_forced=False)
                    | models.Q(
                        is_forced=True,
                        forced_reason__isnull=False,
                        forced_difference__isnull=False,
                    )
                ),
                name="reconciliation_forced_implies_reason_and_amount",
            ),
            # An undo carries its reason and its date, for the same reason a
            # forced close does: without them, an undone session is
            # indistinguishable from one that was never closed.
            #
            # `undone_by` is deliberately not in here, exactly as `closed_by` is
            # not in the forced constraint -- it is SET_NULL, so deleting an
            # employee would retroactively violate it.
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=BankReconciliationStatusChoices.UNDONE)
                    | models.Q(
                        undone_on__isnull=False, undo_reason__isnull=False
                    )
                ),
                name="reconciliation_undone_implies_reason_and_date",
            ),
        ]

    def __str__(self):
        account = self.bank_account.title if self.bank_account_id else "(no account)"
        return f"{account} - {self.statement_ending_date}"

