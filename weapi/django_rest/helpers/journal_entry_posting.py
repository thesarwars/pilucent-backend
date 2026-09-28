"""Undoing a hand-keyed journal entry: the legs, and the balances they moved.

`DELETE /we/journals/{uid}` set `JournalEntry.status = REMOVED` and did nothing
else, and `PATCH` rewrote the legs without touching a balance at all. So the one
document a bookkeeper writes by hand was the one whose three paths were wrong in
three different ways: create moved the balance (correctly, since `6aed4300`),
amend moved the legs and left the balance at the pre-edit figure, and delete
moved neither.

That is the posting-leg mirror rule stated as plainly as it gets. The create
path's direction bug was fixed and its two mirrors were left alone, so two of the
three paths stayed wrong.

## Why the delete posts a reversal instead of just moving the balance back

Moving the balance back on its own would be simpler and would leave the stored
column right -- and would put it at odds with how the balance is derived. The
legs of a REMOVED entry are still in the table, and `account_balance_as_of` and
`audit_ledger` both sum every leg regardless of status. Backing the balance out
without cancelling the legs would make the account *newly* disagree with its own
journal: exactly the drift `repair_account_balances` exists to measure.

So the entry is cancelled the way the five document deletes cancel theirs -- a
second entry, sides flipped, legs marked DELETED -- and the pair nets to zero.
The difference is that the reversal is created REMOVED rather than PUBLISHED.
A manual entry has no separate document to retire: `JournalEntry.status` is both
"is this on the books" and "is this in the list" (`get_status_all()` excludes
REMOVED, and that is what the journal list and the detail view read). Leaving
either half of the pair PUBLISHED would put a deleted entry back on screen; a
REMOVED pair nets to zero on both readings of the ledger and shows on neither.
"""

import logging

from decimal import Decimal

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    get_debit_or_credit,
    update_opening_balance,
)
from common.django_rest.helpers.id_generator import get_unique_id

from journalio.choices import (
    JournalEntryConnectorRequestKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector

logger = logging.getLogger(__name__)


def leg_amount(debit, credit):
    """The one side of a leg that carries a figure."""
    debit = Decimal(str(debit or 0))
    credit = Decimal(str(credit or 0))
    return debit if debit else credit


def move_leg_balance(account, side, amount, *, undo=False):
    """Move `account`'s stored balance for one leg, forwards or backwards.

    `update_opening_balance`'s second argument is add/subtract in the account's
    own direction, NOT an accounting side -- so the operation has to be derived
    from the leg's side against the account's kind. Hard-coding it lands
    correctly on assets and expenses and is backwards on everything else, which
    is the bug `6aed4300` fixed in the create path.

    Refuses to guess. `action_for_side` returns "addition" when it cannot match
    the side, which is a silent wrong answer rather than a safe default -- and
    it is reachable here, because `JournalEntryConnector.kind` carries no model
    default, so a line added through the amend path without a `kind` lands with
    an empty string. Moving a balance on that basis is right for half the
    account kinds and backwards for the other half, with nothing on screen to
    say which. Better to move nothing and say so.
    """
    if account is None or not amount:
        return Decimal("0.000")

    if side not in (get_debit_or_credit(account.kind) or {}).values():
        logger.warning(
            "journal balance: leg on account %s has side %r, which is not a "
            "posting side for a %s account -- balance not moved",
            account.pk, side, account.kind,
        )
        return Decimal("0.000")

    action = action_for_side(account.kind, side)
    if undo:
        action = "substraction" if action == "addition" else "addition"
    update_opening_balance(
        account, balance_operation_for_action(action), amount, 0
    )
    return Decimal(str(amount))


def _reversal_marker(entry):
    """The description a reversal of `entry` carries. Deterministic on purpose.

    It is the only link back to the original: `JournalEntry` has a FK per
    document kind and none for "this entry reverses that one", so the marker is
    what makes the reversal findable at all.
    """
    return f"Reversal of {entry.entry_number or entry.pk}"


def void_manual_journal_entry(entry, *, created_by=None):
    """Cancel a hand-keyed entry: reversing legs, and the balances back.

    Returns the reversing entry, or None when there was nothing to reverse.
    """
    # Found by its own marker, not by looking for DELETED legs on the original.
    #
    # Every other void helper can ask `filter(document=doc)` and get the
    # original AND its reversal, because they share a document FK. A manual
    # journal entry has no document -- the entry IS the document -- so the
    # reversal is an unrelated row and a guard looking at `journal=entry` never
    # sees it. It looked correct and was inert, and calling this twice reversed
    # the original a second time.
    #
    # The two shipped callers both happen to be idempotent by other means (the
    # delete view returns early on REMOVED; the CSV undo nulls its FK), which is
    # why nothing caught it until a test called the helper directly.
    marker = _reversal_marker(entry)
    if JournalEntry.objects.filter(
        company=entry.company_id,
        description=marker,
        status=JournalEntryStatusChoices.REMOVED,
    ).exists():
        logger.info("void_journal_entry: entry %s is already reversed", entry.pk)
        return None

    originals = list(
        JournalEntryConnector.objects.filter(journal=entry)
        .select_related("account")
        .exclude(request_kind=JournalEntryConnectorRequestKindChoices.DELETED)
    )

    connector_data = []
    for original in originals:
        account = original.account
        if account is None:
            continue
        amount = leg_amount(original.debit, original.credit)
        if not amount:
            continue

        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        connector_data.append(
            (account, opposite, amount, account.opening_balance, None)
        )

    if not connector_data:
        logger.info("void_journal_entry: entry %s had no reversible legs", entry.pk)
        return None

    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, entry.company_id, "entry_number", "JE"
        ),
        date=entry.date,
        amount=entry.amount,
        # REMOVED, not PUBLISHED -- see the module docstring. A manual entry has
        # no separate document to retire, so a PUBLISHED half of the pair would
        # put the deleted entry back in the journal list.
        status=JournalEntryStatusChoices.REMOVED,
        kind=entry.kind,
        is_transaction=entry.is_transaction,
        is_journal_entry=True,
        company=entry.company,
        description=marker,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=entry.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        created_by=created_by,
    )

    logger.info(
        "void_journal_entry: entry %s reversed by %s with %s line(s)",
        entry.pk, reversal.pk, len(connector_data),
    )
    return reversal
