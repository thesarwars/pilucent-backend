"""Undoing what a Pay Bills payment posted.

Deleting a Pay Bills payment removed the row and left everything it had done to
the books standing: A/P still relieved, the vendor balance still lowered, the
funding account still credited, the journal entry still on the ledger. The books
said money had been paid that had not.

That is the same shape `SUPPLIER_GAPS.md` D6 describes -- a settlement path and
its unwind disagreeing -- reached from the other end. D6's fix gave the *bills*
back on delete; this gives the *ledger* back.

Written after `credit_note_posting.reverse_credit_note_postings`, which solved
the same problem for credit notes, and deliberately kept in that shape:

* A leg is undone from its OWN stored `kind` against its account's kind, never
  from a literal. That unwinds rows written before the posting sides were
  corrected as readily as rows written after.
* The journal entry is deleted last, by `JournalEntry.delete()`, so its legs go
  with it through CASCADE. Deleting legs first would leave the entry standing
  with nothing under it if anything failed in between.
* The party balance is undone separately, because a supplier is not a
  `ChartOfAccount` and has no kind to resolve a side from.

**A payment has one journal entry and can have many payees**, so a single payee
line is unwound by its legs' `pay_bill_item` tag rather than by deleting the
entry. The entry only goes when nothing is left on it.
"""

import logging
from decimal import Decimal

from common.django_rest.helpers.balance_helpers import (
    get_migration_undo_balance_operation,
    update_opening_balance,
)

from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.helpers.pay_bill_application import unapply_pay_bill_item

logger = logging.getLogger(__name__)


def _reverse_connector(connector):
    """Unwind one leg's effect on its account's stored balance."""
    account = connector.account
    if account is None:
        return False

    amount = connector.debit if connector.debit else connector.credit
    if not amount:
        return False

    update_opening_balance(
        account,
        get_migration_undo_balance_operation(account, connector.kind),
        amount,
        account.opening_balance,
    )
    return True


def _legs_for_item(item):
    """This payee line's legs.

    Falls back to matching on `supplier` for legs written before the
    `pay_bill_item` tag existed. Production holds no Pay Bills rows at all, so
    the fallback covers nothing today -- it is here so the function cannot
    silently reverse *nothing* on an older row and report success.
    """
    tagged = JournalEntryConnector.objects.filter(
        pay_bill_item=item
    ).select_related("account")
    if tagged.exists():
        return tagged

    return JournalEntryConnector.objects.filter(
        journal__pay_bill=item.pay_bill, supplier=item.supplier
    ).select_related("account")


def reverse_pay_bill_item_postings(item):
    """Undo everything one payee line did: the bills, the legs, the balances.

    Returns a summary dict for logging and tests.

    Caller must wrap this in `transaction.atomic()` with whatever follows it. A
    reversal that commits without its delete leaves a payment on the books with
    no effect, which is worse than either state alone.
    """
    summary = {
        "bills_restored": Decimal("0.00"),
        "connectors_reversed": 0,
        "party_balance_reversed": Decimal("0.00"),
        "journal_entries_deleted": 0,
    }

    summary["bills_restored"] = unapply_pay_bill_item(item)

    legs = list(_legs_for_item(item))
    for connector in legs:
        if _reverse_connector(connector):
            summary["connectors_reversed"] += 1

    # Paying a bill SUBTRACTS from what the vendor is owed, so undoing it adds
    # back. CREDIT means "add" to `update_opening_balance` -- not an accounting
    # side; the supplier has no kind for one to be resolved from.
    total = Decimal(str(item.total or 0))
    if item.supplier_id and total:
        update_opening_balance(item.supplier, "credit", total, 0)
        summary["party_balance_reversed"] = total

    entries = {connector.journal_id for connector in legs}
    JournalEntryConnector.objects.filter(
        pk__in=[connector.pk for connector in legs]
    ).delete()

    # The entry belongs to the whole payment, so it only goes when this was the
    # last line on it. Deleting it while another payee's legs are still attached
    # would take those with it through CASCADE.
    for entry in JournalEntry.objects.filter(pk__in=entries):
        if not JournalEntryConnector.objects.filter(journal=entry).exists():
            entry.delete()
            summary["journal_entries_deleted"] += 1

    logger.info(
        "reverse_pay_bill_item_postings: item=%s %s", getattr(item, "pk", None), summary
    )
    return summary


def reverse_pay_bill_postings(pay_bill):
    """The whole payment: every payee line, then whatever entry is left.

    Returns a summary dict for logging and tests.
    """
    summary = {
        "items_reversed": 0,
        "bills_restored": Decimal("0.00"),
        "connectors_reversed": 0,
        "party_balance_reversed": Decimal("0.00"),
        "journal_entries_deleted": 0,
    }

    for item in pay_bill.paybillitem_set.all():
        line = reverse_pay_bill_item_postings(item)
        summary["items_reversed"] += 1
        for key in ("bills_restored", "connectors_reversed",
                    "party_balance_reversed", "journal_entries_deleted"):
            summary[key] += line[key]

    # A payment with no payee lines still has its entry, and an entry whose legs
    # were never tagged leaves stragglers behind. Both are swept here so the
    # document does not outlive its own deletion.
    for entry in JournalEntry.objects.filter(pay_bill=pay_bill):
        for connector in JournalEntryConnector.objects.filter(
            journal=entry
        ).select_related("account"):
            if _reverse_connector(connector):
                summary["connectors_reversed"] += 1
        entry.delete()
        summary["journal_entries_deleted"] += 1

    logger.info(
        "reverse_pay_bill_postings: pay_bill=%s %s",
        getattr(pay_bill, "pk", None), summary,
    )
    return summary
