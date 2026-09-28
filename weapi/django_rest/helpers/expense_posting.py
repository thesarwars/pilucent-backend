"""Reversing an expense's postings instead of erasing them.

`PrivateWeExpenseDetails` is a `RetrieveUpdateDestroyAPIView` and declared no
`perform_destroy`, so `DELETE /we/expenses/{uid}` ran DRF's default
`instance.delete()`. `JournalEntry.expense` is CASCADE and
`JournalEntryConnector.journal` is CASCADE, so the delete took the entry and
every one of its legs with it -- while leaving every `opening_balance` those
legs had moved exactly where it was.

That is the same failure `void_sale_postings` exists to describe, in its own
words: erasing the entry leaves no record of what the document posted, so the
drift it causes cannot even be measured, let alone replayed. Sales were fixed.
Expenses were not, and unlike a sale an expense had no soft-delete either, so
the rows were gone rather than merely stale.

This is the account half of `void_sale_postings`, which is all an expense needs:
its posting path moves chart-of-account balances only -- cost, funding and tax --
and touches no supplier balance and no inventory.
"""

import logging

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
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


def void_expense_postings(expense, *, created_by=None):
    """Post a reversal of everything `expense` posted. Returns the new entry.

    The original entry is left alone. The reversal is a second entry whose lines
    are the originals with their sides flipped, marked DELETED, so the pair nets
    to zero and both stay readable -- a deleted expense can still be explained
    afterwards, which is the whole point of not erasing it.
    """
    entries = list(JournalEntry.objects.filter(expense=expense))
    if not entries:
        logger.info("void_expense_postings: expense %s had nothing posted", expense.pk)
        return None

    # Already reversed. Without this a second call reverses the ORIGINAL legs a
    # second time -- the reversal's own legs are excluded below, so they do not
    # cancel it -- and the stored balances end up overshooting by the full
    # amount in the opposite direction. Reachable: `get_object` does not filter
    # REMOVED, so a repeated DELETE reaches a retired expense.
    if JournalEntryConnector.objects.filter(
        journal__in=entries,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
    ).exists():
        logger.info(
            "void_expense_postings: expense %s is already reversed", expense.pk
        )
        return None

    originals = list(
        JournalEntryConnector.objects.filter(journal__in=entries)
        .select_related("account")
        .exclude(request_kind=JournalEntryConnectorRequestKindChoices.DELETED)
    )

    connector_data = []
    for original in originals:
        account = original.account
        if account is None:
            continue
        amount = original.debit if original.debit else original.credit
        if not amount:
            continue

        # Flip the side this line posted on, and move the stored balance the
        # matching way, so the ledger and the stored figure cannot disagree --
        # the disagreement the old hard delete created on every expense.
        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        connector_data.append(
            (
                account,
                opposite,
                amount,
                account.opening_balance,
                None,
                None,
                original.purchase_item,
            )
        )

    if not connector_data:
        logger.info(
            "void_expense_postings: expense %s had entries but no reversible "
            "lines", expense.pk,
        )
        return None

    template = entries[0]
    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, expense.supplier.company_id, "entry_number", "JE"
        ),
        amount=template.amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=template.kind,
        is_transaction=True,
        is_journal_entry=True,
        company=template.company,
        expense=expense,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        supplier=expense.supplier,
        created_by=created_by,
    )

    logger.info(
        "void_expense_postings: expense %s reversed by entry %s with %s line(s)",
        expense.pk, reversal.pk, len(connector_data),
    )
    return reversal
