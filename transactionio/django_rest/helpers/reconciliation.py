"""Reconciliation, computed against the ledger.

**Phase 3 of `BANK_REGISTER_FIX_PLAN.md`, and it changes what reconciling
means.** Until now every input to the difference came from
`TransactionInformation` -- imported bank-statement rows -- plus two numbers the
client typed. The book never appeared. So the feature reconciled the statement
against itself, and a company with an empty ledger and a clean CSV import closed
at a difference of zero. That is BR-1, and it is why the module could not be
finished incrementally from where it stood.

Measured on production 2026-08-25: ~124 ledger legs across the live money
accounts, **0** of them reconcilable, because `TransactionInformation` is empty.

The candidate set is now `JournalEntryConnector` -- the ledger. Three properties
of that table drive everything below, and two of them were got wrong in the plan
this implements:

1. **Every leg is a delta, and the sum across all of them is the truth.**
   Amend writes a sibling carrying `new - old` (`balance_helpers.amend_leg`);
   void writes a sibling that reverses the original, tagged `DELETED`, to
   "keep the GL trial-balance consistent without deleting history"
   (`void_payroll.py:127-140`). So **nothing is filtered by `request_kind`.**
   The plan said to exclude `DELETED`; doing that would count a voided paycheck
   as though it were still on the books. `account_balance_as_of` -- the existing
   trusted answer to the same question -- also filters none of them.

2. **A document is not a leg.** An amended payment has two legs on the account,
   and the register must show it as one row (industry standard IS-2). So the
   unit of reconciliation here is a **`(journal_entry, account)` group**, summed
   -- never a raw connector row. A fully voided document nets to zero and shows
   as a zero line, which is what the spec's Void-vs-Delete rule asks for.

3. **Which side is money-in depends on the account.** Nothing here hardcodes
   debit as a deposit. `to_natural` decides from the account's kind, so a credit
   card -- a LIABILITY, where a charge is a credit -- reconciles with the same
   arithmetic instead of a mirrored copy of it. `reconciliation.py` already
   warned that the ASSET assumption "has already broken here once".
"""

from decimal import Decimal

from django.db.models import Q, Sum

from rest_framework.exceptions import APIException, ValidationError

from common.django_rest.helpers.ledger_balances import to_natural

from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money

ZERO = Decimal("0.00")


def candidate_connectors(reconciliation, cleared=None):
    """Every ledger leg on this session's bank account, up to the statement date.

    Scoped by company as well as by account. The account alone was enough to
    read another tenant's lines before these endpoints were scoped, and a
    filter that only narrows by account would let that back in.

    Only PUBLISHED entries: a draft is not on the books, so it cannot be
    outstanding against a bank statement (industry standard IS-4).

    `cleared=True` narrows to lines this session has ticked, `False` to lines no
    session has, `None` to both. Note the asymmetry -- "cleared" means ticked by
    **this** session, while "uncleared" means ticked by **no** session, so a
    line another session already reconciled is in neither set and cannot be
    double-counted here.
    """
    from journalio.choices import JournalEntryStatusChoices
    from journalio.models import JournalEntryConnector

    queryset = JournalEntryConnector.objects.filter(
        account=reconciliation.bank_account,
        journal__company=reconciliation.company,
        journal__status=JournalEntryStatusChoices.PUBLISHED,
        date__lte=reconciliation.statement_ending_date,
    )
    # An unsaved session has cleared nothing, and Django refuses an unsaved
    # instance in a related filter -- so without this a preview against a
    # session that has not been written yet dies with a bare ValueError rather
    # than returning the obvious answer.
    if reconciliation.pk is None:
        return queryset.none() if cleared is True else queryset.filter(
            reconciliation__isnull=True
        )

    if cleared is True:
        return queryset.filter(reconciliation=reconciliation)
    if cleared is False:
        return queryset.filter(reconciliation__isnull=True)
    return queryset.filter(
        Q(reconciliation__isnull=True) | Q(reconciliation=reconciliation)
    )


def candidate_documents(reconciliation, cleared=None):
    """One row per document, legs summed -- the tick-list the register shows.

    Grouped by `journal_id` because a document may have several legs on the same
    account once it has been amended, and ticking half of an amendment is not a
    thing a user can mean.
    """
    return (
        candidate_connectors(reconciliation, cleared)
        .values(
            "journal_id",
            "journal__uid",
            "journal__date",
            "journal__kind",
            "journal__entry_number",
            "journal__description",
        )
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("journal__date", "journal_id")
    )


def cleared_totals(reconciliation):
    """`(debits, credits)` this session has ticked, summed off the ledger.

    Returned as raw sides rather than as deposits and payments. For a bank
    account the two coincide -- a deposit is a debit -- but for a credit card
    they invert, and the caller that wants presentation labels should apply
    them itself. The arithmetic below never needs them: it works in the
    account's natural direction.
    """
    totals = candidate_connectors(reconciliation, cleared=True).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    return (
        Decimal(str(totals["debit"] or 0)),
        Decimal(str(totals["credit"] or 0)),
    )


def cleared_movement(reconciliation):
    """What the ticked lines move the account by, in its own direction."""
    debit, credit = cleared_totals(reconciliation)
    return to_natural(debit, credit, reconciliation.bank_account.kind)


def derive_beginning_balance(reconciliation):
    """Where this account stood when the session opens -- derived, not typed.

    Spec s16.2/s16.4: the beginning balance is the prior reconciliation's
    ending balance, not a number the user supplies. While it was client-typed
    the difference was a formula with a free variable on both sides, so any
    session could be made to read 0.00 by typing
    `beginning = stmt_ending - movement`, and the zero-difference rule
    constrained nothing.

    The figure is **the balance already agreed with the bank** -- the last
    closed session's statement ending balance -- and **zero when no session has
    ever closed on this account.**

    Not the ledger balance at the period start, which was the first thing tried
    here and is wrong: it folds activity that has never been reconciled into the
    opening figure, so the difference cancels itself out and the zero-difference
    rule stops constraining anything. That is the same defect as letting the
    client type it, arrived at by a different route.

    Zero for a first reconciliation is the right answer even on an account with
    a posted opening balance: that opening balance is itself a ledger document,
    so it appears in the candidate set and gets reconciled like any other line
    rather than being assumed.
    """
    from transactionio.choices import BankReconciliationStatusChoices
    from transactionio.models import BankReconciliation

    previous = (
        BankReconciliation.objects.filter(
            company=reconciliation.company,
            bank_account=reconciliation.bank_account,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_date__lt=reconciliation.statement_ending_date,
        )
        .exclude(pk=reconciliation.pk)
        .order_by("-statement_ending_date")
        .first()
    )
    if previous:
        return quantize_money(previous.statement_ending_balance)
    return quantize_money(ZERO)


def reconciliation_difference(reconciliation):
    """What the statement claims, less what the ticked book activity explains.

    Zero means the books agree with the bank for everything ticked. Positive
    means the statement holds more than the ticked lines account for; negative,
    less.

    Identical arithmetic to the old formula for a bank account -- there
    `deposits - payments` is exactly `debit - credit` -- but expressed through
    `to_natural`, so a credit card gets the same treatment rather than a
    sign-flipped copy of it.
    """
    return quantize_money(
        Decimal(str(reconciliation.statement_ending_balance))
        - (Decimal(str(reconciliation.beginning_balance)) + cleared_movement(reconciliation))
    )


def reconciled_through(company, bank_account):
    """The statement date of the latest CLOSED session on this account.

    Spec s6.4: "Reconciled through {date} equals the statement end date of the
    latest completed session. It is recomputed on finish and on undo."

    Computed on read, so there is nothing to recompute and nothing to drift --
    the same reasoning `ledger_balances.py` gives for deriving balances rather
    than storing them beside the ledger. "Recomputed on undo" then holds by
    construction rather than by somebody remembering to call something.

    Lines dated on or before this and not cleared are exactly the outstanding
    items the next reconciliation has to explain.

    Returns None when nothing has closed on the account. That is a different
    fact from a date in the past and must not be flattened into one.
    """
    from transactionio.choices import BankReconciliationStatusChoices
    from transactionio.models import BankReconciliation

    return (
        BankReconciliation.objects.filter(
            company=company,
            bank_account=bank_account,
            status=BankReconciliationStatusChoices.CLOSED,
        )
        .order_by("-statement_ending_date")
        .values_list("statement_ending_date", flat=True)
        .first()
    )


def blocking_sessions(reconciliation):
    """CLOSED sessions on this account standing between it and the top of the stack.

    Ordered by `statement_ending_date`, and that choice is the whole of the LIFO
    rule rather than a detail of it.

    `derive_beginning_balance` reads the last CLOSED session with a strictly
    earlier `statement_ending_date` and reads no other ordering -- not
    `reconciled_on`, not `id`. So undoing the session with the greatest
    statement date invalidates nothing, and undoing any other one leaves a later
    session resting on a figure that no longer exists.

    `reconciled_on` would not do. It is a DateField stamped `timezone.now()
    .date()`, so a backlog catch-up closing January, February and March in one
    afternoon gives three ties and no ordering at all -- and popping January
    while February stays closed punches a hole in the reconciled region that
    `reconciled_through` cannot express. `statement_ending_date` is total and
    tie-free, guaranteed by the live-period unique constraint.
    """
    from transactionio.choices import BankReconciliationStatusChoices
    from transactionio.models import BankReconciliation

    return (
        BankReconciliation.objects.filter(
            company=reconciliation.company,
            bank_account=reconciliation.bank_account,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_date__gt=reconciliation.statement_ending_date,
        )
        .exclude(pk=reconciliation.pk)
        .order_by("statement_ending_date")
    )


def reverse_discrepancy_entry(reconciliation, reason, actor=None):
    """Unwind the plug a forced close posted, without deleting its history.

    Appends sibling legs that net the original to zero, tagged
    `request_kind=DELETED` -- the shape `void_payroll` uses and describes as
    keeping "the GL trial-balance consistent without deleting history". The
    entry keeps its identity and its `bank_reconciliation` link, so the shipped
    one-plug-per-session constraint is untouched: one entry, one link, forever.

    The amount comes from the STORED LEGS, netted per account, never from
    `forced_difference`. Two reasons. The stored field can be stale where the
    legs cannot, since the legs are the ledger. And netting makes a second undo
    a no-op instead of a doubling, without needing to recognise its own previous
    reversal.

    The balance operation is `get_migration_undo_balance_operation`, not the
    inverse accounting side. Its name says migration but it answers exactly this
    question -- it derives the operation the original posting used, the same way
    the posting derived it, and inverts that. `update_opening_balance` reads its
    argument as add/subtract rather than as a side, so passing the inverse side
    adds again. `void_payroll` records that mistake doubling every
    debit-natural account.
    """
    from django.db.models import Sum

    from common.django_rest.helpers.balance_helpers import (
        action_for_side,
        get_migration_undo_balance_operation,
        update_opening_balance,
    )
    from journalio.choices import (
        JournalEntryConnectorKindChoices,
        JournalEntryConnectorRequestKindChoices,
    )
    from journalio.django_rest.services.journals import JournalEntryService
    from journalio.models import JournalEntry, JournalEntryConnector

    entry = JournalEntry.objects.filter(bank_reconciliation=reconciliation).first()
    if entry is None:
        return None

    DEBIT = JournalEntryConnectorKindChoices.DEBIT
    CREDIT = JournalEntryConnectorKindChoices.CREDIT

    groups = (
        JournalEntryConnector.objects.filter(journal=entry)
        .values("account_id")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )

    connector_data = []
    total = ZERO
    for group in groups:
        net = Decimal(str(group["debit"] or 0)) - Decimal(str(group["credit"] or 0))
        if not net:
            # Already reversed, or a leg that never moved. Either way there is
            # nothing left to undo, which is what makes a repeat undo harmless.
            continue
        account = _account(group["account_id"])
        original_side = DEBIT if net > 0 else CREDIT
        inverse_side = CREDIT if net > 0 else DEBIT
        amount = abs(net)
        total = max(total, amount)

        update_opening_balance(
            account,
            get_migration_undo_balance_operation(account, original_side),
            amount,
            account.opening_balance,
        )
        connector_data.append(
            (account, action_for_side(account.kind, inverse_side), amount,
             account.opening_balance, None)
        )

    if connector_data:
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total,
            request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
            journal_entry=entry,
            created_by=actor,
            date=entry.date,
            description=f"Reconciliation undone: {reason}",
        )

    # Release EVERY leg of the plug, not only the ones this session ticked.
    #
    # The plug's bank leg is marked cleared by the session that posted it. A
    # later OPEN session may also have ticked it -- LIFO constrains closed
    # successors only, so nothing stops that. Leaving it ticked there would hand
    # that session a cleared `+10` and an unticked `-10` sibling, and because
    # `cleared_totals` sums legs while `candidate_documents` sums groups, its
    # difference would move by 10 while its register row read 0.00.
    JournalEntryConnector.objects.filter(journal=entry).update(
        reconciliation=None, cleared_on=None
    )
    return entry


def _account(account_id):
    from accounts.models import ChartOfAccount

    return ChartOfAccount.objects.get(pk=account_id)


class ReconciliationOutOfOrder(APIException):
    """LIFO refusal. 409, because the request is well-formed and the state is not.

    Carries the blocking sessions as a list rather than a count, per spec s25:
    "attempting an older session first is blocked with the list of dependent
    sessions." A count tells the user they are stuck; the list tells them what
    to undo first.
    """

    status_code = 409
    default_detail = "A later reconciliation must be undone first."
    default_code = "reconciliation_out_of_order"


def undo_reconciliation(reconciliation, reason, actor=None):
    """Unwind a closed session: LIFO, with a reason, releasing its lines.

    Spec s16.7 -- "sessions unwind last-in-first-out; lines revert R to C,
    Reconciled through recalculates, and the undo joins the audit chain with a
    reason."

    Reconciled-through needs no recalculation here because `reconciled_through`
    computes it from CLOSED sessions on read, so moving this one to UNDONE moves
    the badge by construction.

    The caller is responsible for the row lock and the transaction. This is not
    an oversight -- the lock has to span the blocker check and the write, and it
    has to be the same lock the close path takes, or a close and an undo can
    interleave between them.
    """
    from django.utils import timezone

    from transactionio.choices import BankReconciliationStatusChoices

    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(
            {"reason": "Give a reason for undoing this reconciliation. It is "
                       "recorded against the session and against the ledger."}
        )

    if reconciliation.status != BankReconciliationStatusChoices.CLOSED:
        raise ValidationError(
            f"Only a closed reconciliation can be undone; this one is "
            f"{reconciliation.get_status_display().lower()}."
        )

    blockers = list(blocking_sessions(reconciliation))
    if blockers:
        raise ReconciliationOutOfOrder(
            {
                "detail": (
                    "Reconciliations undo last-in-first-out. Undo the later "
                    "sessions on this account first."
                ),
                "blocking_sessions": [
                    {
                        "uid": str(b.uid),
                        "statement_ending_date": b.statement_ending_date.isoformat(),
                        "statement_ending_balance": str(b.statement_ending_balance),
                    }
                    for b in blockers
                ],
            }
        )

    # The plug first, while its legs still carry this session.
    if reconciliation.is_forced:
        reverse_discrepancy_entry(reconciliation, reason, actor=actor)

    # Release the ticked lines: R -> C, not R -> unmarked.
    #
    # `reconciliation` goes, `cleared_on` stays. That pairing IS the status:
    # reconciled means pointing at a closed session, cleared means carrying a
    # tick date and no session. The spec asks for exactly this demotion, and
    # keeping the date means a user who undoes a month does not lose the work of
    # having ticked it.
    released = candidate_connectors(reconciliation, cleared=True).update(
        reconciliation=None
    )

    reconciliation.status = BankReconciliationStatusChoices.UNDONE
    reconciliation.undone_on = timezone.now().date()
    reconciliation.undone_by = actor
    reconciliation.undo_reason = reason
    reconciliation.save(
        update_fields=["status", "undone_on", "undone_by", "undo_reason"]
    )

    # Any OPEN session on this account froze its beginning balance at create
    # from a chain this undo just changed. Re-derive rather than leave it
    # pointing at a figure no closed session asserts any more.
    _redderive_open_sessions(reconciliation)

    return {"released_lines": released, "blocking_sessions": []}


def _redderive_open_sessions(reconciliation):
    from transactionio.choices import BankReconciliationStatusChoices
    from transactionio.models import BankReconciliation

    for session in BankReconciliation.objects.filter(
        company=reconciliation.company,
        bank_account=reconciliation.bank_account,
        status=BankReconciliationStatusChoices.OPEN,
    ).exclude(pk=reconciliation.pk):
        derived = derive_beginning_balance(session)
        if Decimal(str(session.beginning_balance)) != derived:
            session.beginning_balance = derived
            session.save(update_fields=["beginning_balance"])


def build_report_snapshot(reconciliation, actor=None):
    """Freeze what this session reconciled, at the moment it closed. BR-35.

    A reconciliation report cannot be recomputed after the fact, and that is
    arithmetic rather than a storage preference. The ledger keeps moving: an
    amend appends a delta leg to a document this session already cleared, a void
    appends a reversal. Both change what `candidate_documents` returns for a
    period that is already closed, so re-running the report next month gives a
    different answer from the one the bank agreed to, with nothing recording
    that it changed.

    Stored as plain JSON rather than as rows, because this is evidence and not
    data: nothing should join to it, aggregate it, or keep it in step with the
    ledger. It is what was true on the day.

    Amounts are strings. A float would round the very figures the session exists
    to prove agreed to the penny.
    """
    from django.utils import timezone

    debits, credits = cleared_totals(reconciliation)
    documents = list(candidate_documents(reconciliation, cleared=True))

    return {
        "version": 1,
        "frozen_at": timezone.now().isoformat(),
        "frozen_by": getattr(actor, "id", None),
        "account": {
            "uid": str(reconciliation.bank_account.uid),
            "title": reconciliation.bank_account.title,
            "code": reconciliation.bank_account.code,
            "kind": reconciliation.bank_account.kind,
        },
        "statement": {
            "ending_date": reconciliation.statement_ending_date.isoformat(),
            "ending_balance": str(reconciliation.statement_ending_balance),
            "beginning_balance": str(reconciliation.beginning_balance),
        },
        "cleared": {
            "debits": str(debits),
            "credits": str(credits),
            "movement": str(cleared_movement(reconciliation)),
            "document_count": len(documents),
        },
        "difference": str(reconciliation_difference(reconciliation)),
        "forced": {
            "is_forced": reconciliation.is_forced,
            "reason": reconciliation.forced_reason,
            "difference": (
                str(reconciliation.forced_difference)
                if reconciliation.forced_difference is not None
                else None
            ),
        },
        "documents": [
            {
                "uid": str(row["journal__uid"]),
                "date": (
                    row["journal__date"].isoformat() if row["journal__date"] else None
                ),
                "kind": row["journal__kind"],
                "entry_number": row["journal__entry_number"],
                "description": row["journal__description"],
                "debit": str(row["debit"]),
                "credit": str(row["credit"]),
            }
            for row in documents
        ],
    }


def get_or_create_discrepancy_account(company):
    """The Reconciliation Discrepancies account, made on first use.

    Not seeded. A company that never forces a close should not carry the
    account at all, because a balance on it is a standing statement that the
    books and the bank disagreed by that much and nobody found out why.

    Resolved by `system_key`, so a tenant may rename it without breaking this.
    """
    from accounts.choices import (
        ChartOfAccountKindChoices,
        ChartOfAccountStatusChoices,
        ChartOfAccountSystemKeyChoices,
    )
    from accounts.models import ChartOfAccount

    key = ChartOfAccountSystemKeyChoices.RECONCILIATION_DISCREPANCIES
    existing = (
        ChartOfAccount.objects.filter(company=company, system_key=key)
        .exclude(status=ChartOfAccountStatusChoices.REMOVED)
        .first()
    )
    if existing:
        return existing

    return ChartOfAccount.objects.create(
        company=company,
        title="Reconciliation Discrepancies",
        # 8590 per the client numbering scheme: Other Expense sits in
        # 8500-8999 and this is the slot the specification names for it.
        code="8590",
        kind=ChartOfAccountKindChoices.EXPENSES,
        status=ChartOfAccountStatusChoices.ACTIVE,
        system_key=key,
        is_fixed=True,
        description=(
            "Holds amounts a forced bank reconciliation could not explain. A "
            "balance here means the books and the bank disagree by that much."
        ),
    )


def post_reconciliation_discrepancy(reconciliation, difference, created_by=None):
    """Book `difference` so a forced close still leaves the ledger balanced.

    A positive difference means the statement holds more than the ticked lines
    explain, so the book cash rises and the gain lands against the discrepancy
    account; a negative one is the mirror. Neither side is hard-coded: the
    account's own kind decides which action yields the intended side, because
    the bank account is only an ASSET for as long as nobody re-types it, and
    that assumption has already broken here once.
    """
    from common.django_rest.helpers.balance_helpers import (
        action_for_side,
        balance_operation_for_action,
        update_opening_balance,
    )
    from journalio.choices import (
        JournalEntryConnectorKindChoices,
        JournalEntryConnectorRequestKindChoices,
        JournalEntryKindChoices,
        JournalEntryStatusChoices,
    )
    from journalio.django_rest.services.journals import JournalEntryService

    company = reconciliation.company
    bank = reconciliation.bank_account
    discrepancy = get_or_create_discrepancy_account(company)

    amount = abs(difference)
    DEBIT = JournalEntryConnectorKindChoices.DEBIT
    CREDIT = JournalEntryConnectorKindChoices.CREDIT
    bank_side, other_side = (DEBIT, CREDIT) if difference > 0 else (CREDIT, DEBIT)

    connector_data = []
    for account, side in ((bank, bank_side), (discrepancy, other_side)):
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        connector_data.append((account, action, amount, account.opening_balance, None))

    # `object` is keyed to the FK the kind maps to, so the entry is linked to
    # its session by the service rather than patched afterwards -- and because
    # the service does `get_or_create` on that FK, a session cannot accumulate
    # two discrepancy entries.
    entry = JournalEntryService.create_journal_entry(
        amount=amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=JournalEntryKindChoices.BANK_RECONCILIATION,
        is_transaction=True,
        is_journal_entry=True,
        company=company,
        object=reconciliation,
        date=reconciliation.statement_ending_date,
    )

    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=amount,
        request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
        journal_entry=entry,
        created_by=created_by,
        date=reconciliation.statement_ending_date,
    )

    # Mark the plug's own bank leg cleared by the session that posted it.
    #
    # Without this the entry whose entire purpose is to make THIS session agree
    # with its statement lands on the bank account as an uncleared candidate,
    # and every later session is offered it as outstanding activity. It is not
    # outstanding: it was accounted for by the close that created it.
    #
    # The consequence is worse than a stray row, because the two readers of this
    # data disagree on their unit -- `cleared_totals` sums LEGS while
    # `candidate_documents` sums GROUPS. A later session that ticked the plug
    # would move its difference by the plug amount while its register row read
    # 0.00, which is a discrepancy that cannot be seen from the screen it
    # appears on.
    #
    # Only the legs on this session's own account: the discrepancy-account leg
    # is never in this account's candidate set, and flagging it would assert
    # something about a reconciliation of Reconciliation Discrepancies that
    # nobody has run.
    from journalio.models import JournalEntryConnector

    JournalEntryConnector.objects.filter(
        journal=entry, account=reconciliation.bank_account
    ).update(
        reconciliation=reconciliation,
        cleared_on=reconciliation.statement_ending_date,
    )
    return entry
