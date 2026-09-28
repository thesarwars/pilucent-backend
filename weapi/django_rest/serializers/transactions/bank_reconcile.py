from decimal import Decimal
from rest_framework import serializers

from rest_framework.serializers import (
    CharField,
    ChoiceField,
    ModelSerializer,
    SlugRelatedField,
    ListField,
    UUIDField,
    ValidationError,
    Serializer
)

from django.db import transaction
from django.utils import timezone

from accounts.choices import ChartOfAccountStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from accounts.models import ChartOfAccount

from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from transactionio.django_rest.helpers.reconciliation import (
    ReconciliationOutOfOrder,
    blocking_sessions,
    undo_reconciliation,
    build_report_snapshot,
    candidate_connectors,
    derive_beginning_balance,
    post_reconciliation_discrepancy,
    reconciliation_difference,
)

from transactionio.choices import BankReconciliationStatusChoices

from transactionio.models import BankReconciliation


class BankReconciliationListCreateSerializer(
    CompanyScopedRelatedFieldsMixin, ModelSerializer
):
    """Serializer for creating and listing bank reconciliations.

    The mixin is load-bearing, not decoration. `bank_account_uid` resolved
    against every ACTIVE account in the database, so a caller could open a
    reconciliation on another tenant's bank account: `create()` stamps
    `company` from the request, giving a row whose company is theirs and whose
    account is somebody else's. That row then passes a company-scoped lookup --
    so scoping the summary and match endpoints alone would not have closed the
    leak, because the summary reads transactions by `chart_of_account`, not by
    company.
    """

    bank_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    # Narrowed to money accounts. A reconciliation explains a bank statement,
    # so an account with no statement behind it cannot have one -- yet this
    # accepted any ACTIVE selectable account, and half the reconciliations on
    # production point at an expense account (`Gain/Loss on Asset Sale`).
    #
    # `is_money_account` rather than the account-type title: the title is
    # user-editable and matched exactly elsewhere in the product, which a rename
    # breaks silently. See `accounts/migrations/0047_backfill_is_money_account`.
    #
    # Refuses an account positively typed as something else; lets an
    # untyped one through. `account_type` is nullable and legacy charts
    # predate the taxonomy, so refusing NULL would lock those tenants out of
    # deposits and reconciliation entirely -- a regression far worse than
    # the gap being closed. An account typed "Expenses" is refused, which is
    # the production case this exists for (`Gain/Loss on Asset Sale`).
        #
    # This is the transitional stance, not the end state. Phase 2
    # instruments how many accounts are still untyped per tenant; the NULL
    # arm comes out once that number is known to be zero.
    bank_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable()
        .filter(status=ChartOfAccountStatusChoices.ACTIVE)
        .money(),
        write_only=True,
        required=True,
    )

    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = BankReconciliation
        fields = [
            "uid",
            "bank_account",
            "bank_account_uid",
            "beginning_balance",
            "statement_ending_balance",
            "statement_ending_date",
            "status",
            "reconciled_on",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "created_by",
            "created_at",
            "updated_at",
            "reconciled_on",
            # A session reaches CLOSED by surviving `PrivateWeTransactionMatch
            # Serializer.save()`, never by being asked to. While this was
            # writable -- as `is_closed` -- a client could POST it true and get a
            # closed reconciliation that skipped the difference check, the
            # forced-close reason and the Reconciliation Discrepancies posting,
            # with `reconciled_on` NULL and `is_forced` False, so nothing on the
            # row showed it had happened.
            "status",
            # Derived, never supplied. Spec s16.2/s16.4: the beginning balance
            # is the prior reconciliation's ending balance. While a client typed
            # it, the difference was a formula with a free variable on both
            # sides -- any session could be made to read 0.00 by posting
            # `beginning = stmt_ending - movement`, so the zero-difference rule
            # constrained nothing at all.
            #
            # Safe to switch now precisely because the cleanup left 0 sessions:
            # no live form is posting this field, so nothing breaks by ignoring
            # it. It was the open question blocking this change.
            "beginning_balance",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["company"] = company
        validated_data["created_by"] = user.get_employee()
        validated_data["bank_account"] = validated_data.pop("bank_account_uid", None)
        # Placeholder: the real figure needs the saved row to resolve the prior
        # session and the account's position, so it is computed immediately
        # after and written back.
        validated_data["beginning_balance"] = Decimal("0")

        bank_reconciliation = BankReconciliation.objects.create(**validated_data)

        bank_reconciliation.beginning_balance = derive_beginning_balance(
            bank_reconciliation
        )
        bank_reconciliation.save(update_fields=["beginning_balance"])
        return bank_reconciliation


class PrivateWeTransactionMatchSerializer(Serializer):
    """Close a reconciliation.

    A session may only close when the statement agrees with the cleared book
    activity to the penny. This used to close at any difference: it set
    `is_matched` on everything handed to it, stamped `is_closed`, and returned.
    The difference was computed -- correctly -- but only in the summary
    endpoint, which nothing on this path consulted, so a session could be
    declared reconciled while the books and the bank disagreed, leaving no
    record that they ever did.

    Closing out of balance is still possible, because refusing outright would
    strand anyone with a genuine unexplained item. It is now the documented
    exception rather than the silent default: `force` requires a reason, posts
    the difference to Reconciliation Discrepancies so the books stay balanced,
    and marks the session forced.
    """

    # **Journal entries, not statement rows.** This took `transaction_ids`
    # naming `TransactionInformation` -- imported CSV lines, which are not the
    # book. Ticking one said nothing about the ledger, which is BR-1.
    #
    # A breaking change to the request body, made deliberately and cheaply: the
    # endpoint was a 403 for every non-admin until 2026-08-24, and the cleanup
    # left 0 reconciliations, so nothing has ever successfully called it.
    journal_entry_ids = ListField(child=CharField())
    reconciliation_id = CharField()
    force = serializers.BooleanField(required=False, default=False)
    forced_reason = CharField(required=False, allow_blank=True)

    def validate(self, data):
        """Resolve the reconciliation and its lines, both scoped to the caller.

        The company filter here is the point of the method. This looked up the
        reconciliation by `uid` alone and then checked each transaction against
        `reconciliation.company` -- which compares the two *arguments* to each
        other and never to the person asking. The check therefore passed for a
        caller with no relationship to either, and `save()` went on to close
        another company's reconciliation and flip `is_matched` on their
        transactions.
        """
        company = self.context["request"].user.get_active_company()

        try:
            reconciliation = BankReconciliation.objects.get(
                uid=data["reconciliation_id"], company=company
            )
        except BankReconciliation.DoesNotExist:
            raise ValidationError("Reconciliation not found.")

        if reconciliation.status != BankReconciliationStatusChoices.OPEN:
            raise ValidationError(
                f"This reconciliation is {reconciliation.get_status_display().lower()}, "
                f"so it cannot be closed. Undoing a closed session frees its "
                f"period; reconciling it again is a new session."
            )

        uids = list(dict.fromkeys(data["journal_entry_ids"]))
        if not uids:
            # BR-6. An empty list used to mean "close having ticked nothing",
            # which passes the zero-difference gate whenever the statement
            # happens to equal the beginning balance -- a session that
            # reconciled no lines at all and recorded itself as clean.
            raise ValidationError(
                {"journal_entry_ids": "Tick at least one document to reconcile."}
            )

        # Resolved from the CANDIDATE SET, not from the entry table at large.
        # That single predicate carries every scope this endpoint needs: the
        # caller's company, this session's bank account, published entries only,
        # and nothing dated after the statement. A document that fails any of
        # them is not merely unauthorised, it is not reconcilable here.
        candidates = candidate_connectors(reconciliation)
        found = set(
            candidates.filter(journal__uid__in=uids).values_list(
                "journal__uid", flat=True
            )
        )
        missing = [u for u in uids if str(u) not in {str(f) for f in found}]
        if missing:
            raise ValidationError(
                {
                    "journal_entry_ids": (
                        "Not reconcilable against this session: "
                        f"{', '.join(str(m) for m in missing)}. A document must "
                        "post to this bank account, be published, be dated on or "
                        "before the statement date, and not already be cleared by "
                        "another reconciliation."
                    )
                }
            )

        self.reconciliation = reconciliation
        self.journal_uids = uids
        return data

    @transaction.atomic
    def save(self, **kwargs):
        """Tick the ledger legs, check the difference, then close.

        The order matters. The difference is a function of what is ticked, so it
        can only be evaluated once this session's lines are marked -- which is
        why the check lives here rather than in `validate()`. The whole method
        is atomic, so a refusal rolls the ticks back.
        """
        # BR-14. Re-read under a row lock before doing anything.
        #
        # `validate()` checked `is_closed` and `save()` acts on it, and nothing
        # held the row in between. Two concurrent closes both passed the check,
        # both ticked, and both closed -- the second overwriting the first's
        # `reconciled_on` and, on a forced close, posting a second discrepancy
        # entry for the same unexplained amount. The re-check below is not
        # redundant with `validate()`: it is the half that happens while the row
        # is held.
        # The whole ACCOUNT's set, not just this row, because the thing that
        # makes a close illegal is a DIFFERENT row: a session for a later
        # statement period that is already closed. Locking only this row would
        # let a close and an undo, or two closes on adjacent periods, interleave
        # between the check and the write. Any would-be blocker already exists
        # as a row before it can be closed, so this serialises them with no
        # phantom -- and it does not touch the ledger, so ordinary posting to
        # the bank account is unaffected.
        list(
            BankReconciliation.objects.select_for_update().filter(
                company=self.reconciliation.company,
                bank_account=self.reconciliation.bank_account,
            )
        )
        locked = BankReconciliation.objects.get(pk=self.reconciliation.pk)
        if locked.status != BankReconciliationStatusChoices.OPEN:
            raise ValidationError(
                "This reconciliation was closed by another request while this "
                "one was in flight."
            )
        self.reconciliation = locked

        # Closes are LIFO too, and this is not symmetry for its own sake.
        #
        # A LIFO undo rule with a non-LIFO close rule is not a stack. Closing
        # January while February is already closed makes February's stored
        # `beginning_balance` permanently disagree with what
        # `derive_beginning_balance` computes for it -- February opened from a
        # chain that did not yet contain January -- and no undo is involved in
        # producing that. The invariant this protects is one sentence: for every
        # closed session, its stored beginning balance is the one its own chain
        # derives.
        out_of_order = list(blocking_sessions(self.reconciliation))
        if out_of_order:
            raise ReconciliationOutOfOrder(
                {
                    "detail": (
                        "A later statement period on this account is already "
                        "reconciled. Close periods in order, or undo the later "
                        "ones first."
                    ),
                    "blocking_sessions": [
                        {
                            "uid": str(b.uid),
                            "statement_ending_date": b.statement_ending_date.isoformat(),
                        }
                        for b in out_of_order
                    ],
                }
            )

        # Re-derive under the lock. The figure was frozen when the session was
        # created, and the chain may have moved since -- another period closed,
        # or one undone.
        self.reconciliation.beginning_balance = derive_beginning_balance(
            self.reconciliation
        )

        today = timezone.now().date()

        # Tick every leg of each named document. Legs, plural: an amended
        # payment has a second leg on the same account carrying the delta, and
        # clearing half of an amendment is not a thing a user can mean.
        candidate_connectors(self.reconciliation, cleared=False).filter(
            journal__uid__in=self.journal_uids
        ).update(reconciliation=self.reconciliation, cleared_on=today)

        # And UNtick anything this session had marked that is not in the list.
        # The old path only ever set `is_matched=True`, so a tick could not be
        # taken back and a mistake was permanent. Submitting the list again
        # without a document now releases it.
        candidate_connectors(self.reconciliation, cleared=True).exclude(
            journal__uid__in=self.journal_uids
        ).update(reconciliation=None, cleared_on=None)

        difference = reconciliation_difference(self.reconciliation)
        if difference != 0:
            if not self.validated_data.get("force"):
                raise ValidationError(
                    {
                        "difference": (
                            f"This reconciliation is out of balance by "
                            f"{difference}. Tick the remaining documents, or "
                            f"resubmit with force and a reason to post the "
                            f"difference to Reconciliation Discrepancies."
                        ),
                        "amount": str(difference),
                    }
                )

            reason = (self.validated_data.get("forced_reason") or "").strip()
            if not reason:
                raise ValidationError(
                    {
                        "forced_reason": (
                            "Give a reason for closing out of balance. It is "
                            "recorded against the session and the journal entry."
                        )
                    }
                )

            post_reconciliation_discrepancy(
                self.reconciliation,
                difference,
                created_by=self.context["request"].user.get_employee(),
            )
            self.reconciliation.is_forced = True
            self.reconciliation.forced_reason = reason
            self.reconciliation.forced_difference = difference

        self.reconciliation.status = BankReconciliationStatusChoices.CLOSED
        # Who signed it off, which is not necessarily who opened it.
        self.reconciliation.closed_by = self.context["request"].user.get_employee()
        # `timezone.now()`, not `datetime.today()` -- BR-28. The latter reads
        # the server's local clock, so a close just before midnight UTC could be
        # stamped with the wrong day relative to every other date on the record.
        self.reconciliation.reconciled_on = today
        # BR-35. Freeze the report before anything else can move the ledger
        # under it -- an amend or a void on a cleared document would otherwise
        # change what this period reports, months after the bank agreed to it.
        self.reconciliation.report_snapshot = build_report_snapshot(
            self.reconciliation, actor=self.reconciliation.closed_by
        )
        self.reconciliation.save()
        return self.reconciliation


class PrivateWeReconciliationLineTickSerializer(Serializer):
    """Tick or untick documents against an OPEN session, without closing it.

    Until this existed, `reconciliation` and `cleared_on` were written in
    exactly two places -- closing a session and undoing one -- and closing is
    atomic with ticking. So a reconciliation could not be saved half-done: a
    user who ticked forty lines and reloaded the page lost forty ticks, and the
    only way to record any progress was to balance to the penny in one sitting.

    Writes the same two columns the close path writes, so nothing new has to
    interpret them. A line ticked here carries this session's uid while the
    session is still OPEN, which the register already renders as **C** --
    reconciled is a line pointing at a *closed* session, and this one is not
    closed yet.

    Both actions are idempotent, because this backs a checkbox. Clearing what is
    already clear, or unclearing what was never cleared, succeeds and changes
    nothing; only a document that could not be ticked at all -- wrong account,
    unpublished, dated after the statement, or already cleared by a *different*
    session -- is refused, and refused by name.
    """

    journal_uids = ListField(child=UUIDField(), allow_empty=False)
    action = ChoiceField(choices=["clear", "unclear"])

    def validate(self, data):
        company = self.context["request"].user.get_active_company()

        try:
            reconciliation = BankReconciliation.objects.get(
                uid=self.context["uid"], company=company
            )
        except BankReconciliation.DoesNotExist:
            raise ValidationError("Reconciliation not found.")

        if reconciliation.status != BankReconciliationStatusChoices.OPEN:
            raise ValidationError(
                f"This reconciliation is "
                f"{reconciliation.get_status_display().lower()}, so its lines "
                f"cannot be changed. Undo it to reopen the period."
            )

        uids = list(dict.fromkeys(data["journal_uids"]))

        # Validated against the whole candidate set -- uncleared plus already
        # ticked by this session -- rather than against the set the action will
        # move. That is what makes both actions idempotent: re-clearing a
        # ticked document is a no-op rather than "not reconcilable".
        candidates = candidate_connectors(reconciliation)
        found = {
            str(value)
            for value in candidates.filter(journal__uid__in=uids).values_list(
                "journal__uid", flat=True
            )
        }
        missing = [str(u) for u in uids if str(u) not in found]
        if missing:
            raise ValidationError(
                {
                    "journal_uids": (
                        "Not reconcilable against this session: "
                        f"{', '.join(missing)}. A document must post to this "
                        "bank account, be published, be dated on or before the "
                        "statement date, and not already be cleared by another "
                        "reconciliation."
                    )
                }
            )

        self.reconciliation = reconciliation
        self.journal_uids = uids
        return data

    @set_auditlog_actor
    @transaction.atomic
    def save(self, **kwargs):
        """Move the ticks, then report where the session now stands.

        Locked and re-checked for the same reason the close path is: the status
        was read in `validate()` and is acted on here, and nothing held the row
        in between -- so a tick could otherwise land on a session that another
        request closed in the gap, writing this session's uid onto a line of a
        reconciliation that is already finished.
        """
        locked = (
            BankReconciliation.objects.select_for_update()
            .filter(pk=self.reconciliation.pk)
            .first()
        )
        if locked is None or locked.status != BankReconciliationStatusChoices.OPEN:
            raise ValidationError(
                "This reconciliation was closed by another request while this "
                "one was in flight."
            )
        self.reconciliation = locked

        action = self.validated_data["action"]
        if action == "clear":
            # Filtered to the not-yet-cleared so a re-tick does not restamp
            # `cleared_on` with a later date than the day the work was done.
            moved = (
                candidate_connectors(self.reconciliation, cleared=False)
                .filter(journal__uid__in=self.journal_uids)
                .update(
                    reconciliation=self.reconciliation,
                    cleared_on=timezone.now().date(),
                )
            )
        else:
            moved = (
                candidate_connectors(self.reconciliation, cleared=True)
                .filter(journal__uid__in=self.journal_uids)
                .update(reconciliation=None, cleared_on=None)
            )

        cleared = candidate_connectors(self.reconciliation, cleared=True)
        return {
            "action": action,
            "lines_changed": moved,
            "cleared_documents": cleared.values("journal__uid").distinct().count(),
            "cleared_lines": cleared.count(),
            "difference": f"{reconciliation_difference(self.reconciliation):.3f}",
        }


class ReconciliationDocumentSerializer(serializers.Serializer):
    """One reconcilable document, its legs on this account already summed.

    A document, not a journal line: an amended payment has a second leg
    carrying the delta, and the register must render it as one row (industry
    standard IS-2). `amount` is the movement in the account's own direction, so
    a credit card reads correctly without a mirrored code path.
    """

    uid = serializers.UUIDField(source="journal__uid")
    date = serializers.DateField(source="journal__date")
    kind = serializers.CharField(source="journal__kind")
    entry_number = serializers.CharField(
        source="journal__entry_number", allow_null=True
    )
    description = serializers.CharField(
        source="journal__description", allow_null=True
    )
    debit = serializers.DecimalField(max_digits=19, decimal_places=3)
    credit = serializers.DecimalField(max_digits=19, decimal_places=3)
    amount = serializers.DecimalField(max_digits=19, decimal_places=3)


class PrivateWeReconciliationUndoSerializer(Serializer):
    """Undo a closed reconciliation. Spec s16.7.

    The only exit a closed session had was none: `validate()` refused to reopen
    one and said so, and a mistake was therefore permanent -- with the ledger
    legs still pointing at it, so the lines could never be reconciled again
    either. That is BR-12.

    Undo is LIFO and terminal. The session keeps its row and its close details,
    moves to UNDONE, and frees its statement period for a fresh session; it is
    never reopened in place. That matters beyond tidiness: reopening in place
    would let a second forced close hit `get_or_create` on the same
    `bank_reconciliation` FK, giving an entry whose header amount is the first
    close's figure while its legs net to the second's.
    """

    reason = CharField()

    def validate(self, data):
        company = self.context["request"].user.get_active_company()
        try:
            reconciliation = BankReconciliation.objects.get(
                uid=self.context["uid"], company=company
            )
        except BankReconciliation.DoesNotExist:
            raise ValidationError("Reconciliation not found.")
        self.reconciliation = reconciliation
        return data

    @transaction.atomic
    @set_auditlog_actor
    def save(self, **kwargs):
        """Lock the account's sessions, then unwind.

        The same lock the close path takes, and for the same reason: the row
        that makes an undo illegal is a different row, so a lock on this one
        alone would let a close of a later period slip in between the blocker
        check and the write.
        """
        list(
            BankReconciliation.objects.select_for_update().filter(
                company=self.reconciliation.company,
                bank_account=self.reconciliation.bank_account,
            )
        )
        locked = BankReconciliation.objects.get(pk=self.reconciliation.pk)
        actor = self.context["request"].user.get_employee()
        result = undo_reconciliation(
            locked, self.validated_data["reason"], actor=actor
        )
        locked.refresh_from_db()
        self.reconciliation = locked
        return result


class BankReconciliationSummarySerializer(serializers.Serializer):
    """The reconcile workspace, served from the ledger.

    `matched_transactions` / `unmatched_transactions` are gone, and with them
    the last read of `TransactionInformation` on this path. They listed imported
    CSV rows, so the workspace showed the statement to be reconciled against
    itself. The replacements list book documents.

    A breaking response change, made deliberately: this endpoint raised
    AttributeError -- a 500 -- for every non-admin until 2026-08-24, and the
    2026-08-25 cleanup left 0 reconciliations, so no client has ever read a
    successful response from it.
    """

    uid = serializers.UUIDField()
    bank_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    statement_ending_balance = serializers.DecimalField(max_digits=19, decimal_places=3)
    statement_ending_date = serializers.DateField()
    beginning_balance = serializers.DecimalField(max_digits=19, decimal_places=3)
    cleared_balance = serializers.DecimalField(max_digits=19, decimal_places=3)
    difference = serializers.DecimalField(max_digits=19, decimal_places=3)
    payments_total = serializers.DecimalField(max_digits=19, decimal_places=3)
    deposits_total = serializers.DecimalField(max_digits=19, decimal_places=3)
    cleared_documents = ReconciliationDocumentSerializer(many=True)
    uncleared_documents = ReconciliationDocumentSerializer(many=True)
