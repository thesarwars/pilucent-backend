"""Reverse what a credit note posted, so it can be posted again from its lines.

This is the credit-note half of the pattern `sale_posting` already established:
a document knows how to post itself from its persisted state, so an amendment is
"reverse, change, repost" rather than a hand-written patch of the rows the last
posting happened to leave behind.

WHY. `PrivateCreditNoteItemDetailsSerializer.update` is ~400 lines of
patch-in-place, and an audit found 26 defects in it that are wrong on the
conventional account kinds -- balances moved with no journal row written, the same
income figure moved twice by two blocks, inventory diverging from its own leg in
both quantity branches, and three blocks that cannot execute at all. The sale side
reached exactly this point and its fix says why patching was never going to work:

    "This was ~265 lines that tried to unwind a single line's postings by hand...
     It is the same patch-in-place approach that made amendment wrong, with the
     same failure modes -- it could only find the connectors it recognised, and
     anything it missed stayed in the ledger."

Reposting cannot miss a connector, because it does not look for connectors. It
throws the whole entry away and builds a new one from the document.

WHAT A CREDIT NOTE MOVES, and therefore what has to come back:

    journal connectors      every leg's effect on its account's stored balance
    customer / supplier     moved alongside A/R or A/P at post time
    product quantity        SALE returns goods to stock, PURCHASE removes them
    purchase item quantity  a SALE note puts the units back on the FIFO layer

The quantity halves are the ones a connector-walk cannot see, which is the other
reason the old approach could not be made complete.
"""

import logging
from decimal import Decimal

from common.django_rest.helpers.balance_helpers import (
    get_migration_undo_balance_operation,
    update_opening_balance,
)
from common.django_rest.helpers.quantity_helpers import update_quantity

from creditnoteio.choices import CreditNoteKindChoices

from journalio.choices import JournalEntryConnectorKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

logger = logging.getLogger(__name__)


def record_credit_note_movement(
    credit_note, line, product, quantity, *, inbound, reverse=False,
    unit_price=None, note=None,
):
    """Append the stock-ledger movement for one credit-note line.

    Every credit-note path that moved stock moved it in `Product.quantity`
    alone, so a return left no trace of which lot the goods went back to or came
    out of -- see `STOCK_LEDGER_DECISIONS.md` §4. They all route through here so
    the pattern lives once rather than in six places, which is how the sale-side
    version came to be wrong in two of them.

    `inbound` says which way the goods travel, not which kind of note it is:

    * **SALE note** -- the customer sends goods back. They return to the layers
      the sale consumed, at the cost it consumed them at, as NEGATIVE slices.
      Units matching no consumption are booked as `ADJUSTMENT_IN` at
      `unit_price`: real stock this ledger has no source for, which is what a
      credit note against a pre-ledger sale produces.

    * **PURCHASE note** -- goods go back to the supplier. They leave the oldest
      layers first, as positive consumption slices. Units no layer accounts for
      become a fallback slice at `unit_price` rather than being dropped.

    `reverse` is for the amend and void paths -- six of the eight sites in this
    module's scope are one or the other, which is the standing posting-leg
    mirror rule. It flips nothing about the arithmetic; it only records the row
    as a `REVERSAL`, which is deliberately not a cost layer, so undoing a note
    can never mint stock. The direction still says which way the goods travel:
    undoing a SALE note sends them back out, undoing a PURCHASE note brings them
    back in.

    Best-effort, like every other writer here: a ledger failure must not take
    the posting down with it.
    """
    quantity = int(quantity or 0)
    if product is None or not quantity:
        return

    try:
        from stockio.choices import StockMovementTypeChoices
        from stockio.django_rest.services.stock_movement import (
            consumption_slices,
            record_stock_movement,
            reversal_slices,
        )

        def append(movement_type, signed_quantity, layer_slices=None):
            if not signed_quantity and not layer_slices:
                return
            record_stock_movement(
                company=credit_note.company,
                product=product,
                date=credit_note.date,
                movement_type=movement_type,
                signed_quantity=signed_quantity,
                rate=unit_price,
                layer_slices=layer_slices,
                created_by=credit_note.created_by,
                credit_note_item=line,
                note=note,
            )

        if inbound:
            slices, unplaced = reversal_slices(product, quantity)
            append(
                StockMovementTypeChoices.REVERSAL
                if reverse
                else StockMovementTypeChoices.SALE_RETURN,
                quantity - unplaced,
                slices,
            )
            # Only a genuine return can produce unattributable stock. A reversal
            # is undoing a row this ledger wrote, so there is always something
            # to give back to; if there is not, the honest record is nothing.
            if unplaced and not reverse:
                append(StockMovementTypeChoices.ADJUSTMENT_IN, unplaced)
        else:
            slices, unplaced = consumption_slices(
                product, quantity, fallback_rate=unit_price or 0
            )
            append(
                StockMovementTypeChoices.REVERSAL
                if reverse
                else StockMovementTypeChoices.PURCHASE_RETURN,
                -(quantity - unplaced),
                slices,
            )
    except Exception:
        logger.exception(
            "stock ledger: failed to record credit note %s line %s for product %s",
            getattr(credit_note, "pk", None),
            getattr(line, "pk", None),
            getattr(product, "pk", None),
        )


def credit_note_lines(credit_note):
    """The lines that posted, in a stable order."""
    return list(credit_note.creditnoteitem_set.all().order_by("id"))


def _reverse_connector(connector):
    """Unwind one connector's effect on its account's stored balance.

    The undo comes from the leg's own stored `kind` against its account's kind,
    never from a literal, so this also unwinds rows written before the posting
    sides were corrected -- which is most of what is on the books right now.
    """
    account = connector.account
    if account is None:
        return False

    # Exactly one side is non-zero.
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


def _reverse_party_balance(credit_note):
    """Unwind the customer or supplier balance the note moved.

    A SALE note lowers what the customer owes and a PURCHASE note lowers what is
    owed to the supplier -- both SUBTRACT at post time, so both are added back
    here. `Customer` and `Supplier` have no account kind, so there is no side to
    resolve: the undo is simply the opposite operation.

    A reversal that skipped this would leave the party's own balance carrying a
    credit note that no longer exists, which no connector-walk would reveal
    because the party balance has no journal row.
    """
    party = (
        credit_note.customer
        if credit_note.kind == CreditNoteKindChoices.SALE
        else credit_note.supplier
    )
    if party is None:
        return Decimal("0.00")

    total = Decimal(str(credit_note.total or 0))
    if total == 0:
        return Decimal("0.00")

    # Posting used DEBIT (subtract); CREDIT adds it back.
    update_opening_balance(
        party,
        JournalEntryConnectorKindChoices.CREDIT,
        total,
        party.opening_balance,
    )
    return total


def restore_credit_note_quantities(credit_note):
    """Undo the stock movement, including the FIFO layer a SALE note refilled.

    A SALE credit note takes goods back from the customer: `update_quantity(...,
    "addition", ...)` at post time, and the returned units are added to the
    purchase item they came from so they can be sold again. A PURCHASE credit
    note sends goods back to the supplier, so its posting DEDUCTS.

    Both are undone here. The purchase-item half matters most: it is invisible to
    anything that walks journal connectors, so an amendment that reposted without
    it would hand the same units back twice.
    """
    restored_units = 0
    restored_layers = 0
    is_sale = credit_note.kind == CreditNoteKindChoices.SALE

    for line in credit_note_lines(credit_note):
        product = line.product
        quantity = int(line.quantity or 0)
        if product is None or not quantity:
            continue

        update_quantity(
            product,
            "deduction" if is_sale else "addition",
            quantity,
            0,
        )
        restored_units += quantity

        # Undoing a SALE note sends the goods back out to the customer; undoing
        # a PURCHASE note brings them back from the supplier. Recorded as a
        # REVERSAL either way, which is deliberately not a cost layer, so voiding
        # a note can never mint stock at a price nobody paid.
        record_credit_note_movement(
            credit_note, line, product, quantity,
            inbound=not is_sale, reverse=True,
            note="Reversed by a void or amendment of the credit note.",
        )

        if not is_sale:
            continue

        # Take the returned units back off the lot the posting credited them to.
        for connector in JournalEntryConnector.objects.filter(
            credit_note_item=line, purchase_item__isnull=False
        ).select_related("purchase_item"):
            purchase_item = connector.purchase_item
            if purchase_item is None:
                continue
            purchase_item.quantity = (purchase_item.quantity or 0) - quantity
            purchase_item.opening_quantity = (
                purchase_item.opening_quantity or 0
            ) - quantity
            purchase_item.save(update_fields=["quantity", "opening_quantity"])
            restored_layers += 1
            break

    return restored_units, restored_layers


def reverse_credit_note_postings(credit_note, *, restore_quantities=True):
    """Undo everything `credit_note` posted, leaving it ready to post again.

    Returns a summary dict for logging and tests.

    Caller must wrap this in `transaction.atomic()` together with the repost --
    a reversal that commits without its repost leaves the document with no
    journal at all.

    The journal entries are deleted last and by `JournalEntry.delete()`, not by
    deleting connectors: the connector rows go with the entry through its own
    CASCADE, and going the other way round would leave the entry standing with
    no legs if anything failed in between.
    """
    summary = {
        "connectors_reversed": 0,
        "journal_entries_deleted": 0,
        "party_balance_reversed": Decimal("0.00"),
        "units_restored": 0,
        "layers_restored": 0,
    }

    journal_entries = list(JournalEntry.objects.filter(credit_note=credit_note))
    connectors = list(
        JournalEntryConnector.objects.filter(
            journal__in=journal_entries
        ).select_related("account")
    )

    for connector in connectors:
        if _reverse_connector(connector):
            summary["connectors_reversed"] += 1

    summary["party_balance_reversed"] = _reverse_party_balance(credit_note)

    if restore_quantities:
        units, layers = restore_credit_note_quantities(credit_note)
        summary["units_restored"] = units
        summary["layers_restored"] = layers

    for journal_entry in journal_entries:
        journal_entry.delete()
        summary["journal_entries_deleted"] += 1

    logger.info(
        "reverse_credit_note_postings: credit_note=%s %s",
        getattr(credit_note, "id", None),
        summary,
    )
    return summary
