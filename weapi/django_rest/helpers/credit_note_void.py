"""Undoing a credit note: the allocations, the stock, the layers, the legs.

`DELETE /we/credit-notes/{uid}` set the document's status to REMOVED and did
nothing else. The note's A/R or A/P leg stayed PUBLISHED, so a credit that no
longer existed went on reducing what a customer owed or what was owed to a
supplier; the goods it moved stayed moved; and the customer or supplier balance
kept the figure the posting put there.

**Why this is not `reverse_credit_note_postings`.** That helper exists in
`credit_note_posting.py` and looks like the answer, but it is built for a
different contract -- "reverse, change, repost" -- and it ends by calling
`JournalEntry.delete()`. `JournalEntryConnector.journal` is CASCADE, so that
erases every leg, and the cascade reaches further: file attachments, tags, and
the `cleared_on`/`reconciliation` markers that live ON the leg, which silently
unpicks any reconciliation that had ticked it. Erasing the original is precisely
the defect the expense delete was fixed for. It is also dead code -- nothing in
production has ever called it -- which is how the dead branch described below
survived unnoticed.

So this posts a **second** entry with the sides flipped, marked DELETED, and
leaves the original readable, the way the four shipped delete paths do.

**Two refusals rather than a reversal.**

*Applied credits.* Applying a credit note writes no journal leg at all -- the
only record is a payment-item row, plus (on the purchase side) a decrement of
the stored `total`. So there is nothing to flip: unwinding an application means
reaching into a second, separately posted document and rewriting its totals with
no ledger movement to explain it. Delete the payment first; that path exists on
both sides now.

*Consumed stock.* A SALE note's returned goods become spendable again, in two
distinct ways -- units it cannot attribute to any prior consumption are booked
as `ADJUSTMENT_IN`, which IS a cost layer, and the units it can attribute are
handed back to their original layers as negative slices. Either way a later
document can have spent them, and once it has there is no honest reversal.

**Driven off `StockMovement`, not off the note's lines.** The SALE branch of the
line PATCH changes a line's quantity without moving `Product.quantity` or writing
any movement, so after an edit the lines no longer describe what posted. The same
argument as `stock_adjustment_posting`, for the same reason.
"""

import logging

from decimal import Decimal

from rest_framework.serializers import ValidationError

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.id_generator import get_unique_id

from creditnoteio.choices import CreditNoteKindChoices

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector

from purchaseio.choices import (
    PurchasePaymentItemModelKindChoices,
    PurchasePaymentStatusChoices,
)

from salesio.choices import (
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveStatusChoices,
)

from stockio.choices import StockMovementTypeChoices
from stockio.django_rest.services.stock_movement import record_stock_movement
from stockio.models import StockMovement, StockMovementLayerConsumption

logger = logging.getLogger(__name__)


RECEIVABLE_TITLE = "Accounts Receivable (A/R)"
PAYABLE_TITLE = "Accounts Payable (A/P)"

# Everything a credit note itself writes. REVERSAL is deliberately absent: the
# rows written below carry `credit_note_item` too, which is what makes a voided
# note recognisable as voided -- and what would make an FK-only query reverse
# its own reversals.
POSTED_MOVEMENT_TYPES = (
    StockMovementTypeChoices.SALE_RETURN,
    StockMovementTypeChoices.PURCHASE_RETURN,
    StockMovementTypeChoices.ADJUSTMENT_IN,
)


class CreditNoteApplied(ValidationError):
    """409-shaped refusal: a payment has already spent this credit."""


class CreditNoteStockConsumed(ValidationError):
    """409-shaped refusal: stock this note returned has since been used."""


# ---------------------------------------------------------------------------
# Refusal 1: the credit has been spent
# ---------------------------------------------------------------------------


def applied_allocations(credit_note):
    """Live payments that have drawn on this credit. `[(kind, uid, amount)]`.

    A payment that has been deleted does not count -- its rows survive the
    delete, and treating them as live would make a note unfreeable forever.
    That is the same exclusion `get_sale_remaining_balance` now makes.
    """
    applied = []

    for item in (
        credit_note.salepaymentreceiveitem_set.filter(
            model_kind=SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE
        )
        .exclude(
            sale_payment_receive__status=SalePaymentReceiveStatusChoices.REMOVED
        )
        .select_related("sale_payment_receive")
    ):
        amount = Decimal(str(item.used_total or 0))
        if amount and item.sale_payment_receive_id:
            applied.append(
                ("customer payment", str(item.sale_payment_receive.uid), amount)
            )

    for item in (
        credit_note.purchasepaymentitem_set.filter(
            model_kind=PurchasePaymentItemModelKindChoices.CREDIT_NOTE
        )
        .exclude(purchase_payment__status=PurchasePaymentStatusChoices.REMOVED)
        .select_related("purchase_payment")
    ):
        amount = Decimal(str(item.used_total or 0))
        if amount and item.purchase_payment_id:
            applied.append(
                ("supplier payment", str(item.purchase_payment.uid), amount)
            )

    return applied


def assert_credit_not_applied(credit_note):
    """Raise unless nothing has spent this credit yet."""
    applied = applied_allocations(credit_note)
    if not applied:
        return

    raise CreditNoteApplied(
        {
            "code": "CREDIT-NOTE-APPLIED",
            "message": (
                "This credit note cannot be deleted: it has already been "
                f"applied to {len(applied)} payment(s). Delete those payments "
                "first — doing so returns the credit — then delete the note."
            ),
            "payments": [
                {"kind": kind, "uid": uid, "applied": float(amount)}
                for kind, uid, amount in applied
            ],
        }
    )


# ---------------------------------------------------------------------------
# Refusal 2: the stock has been spent
# ---------------------------------------------------------------------------


def credit_note_movements(credit_note):
    """This note's own inventory rows, oldest first. Never its REVERSALs."""
    return list(
        StockMovement.objects.filter(
            credit_note_item__credit_note=credit_note,
            movement_type__in=POSTED_MOVEMENT_TYPES,
        )
        .select_related("product", "credit_note_item")
        .order_by("id")
    )


def _own_reversals(credit_note):
    return StockMovement.objects.filter(
        credit_note_item__credit_note=credit_note,
        movement_type=StockMovementTypeChoices.REVERSAL,
    )


def _layer_unit_cost(movement):
    """What `ledger_layers` would price this layer at, derived the same way."""
    unit_cost = Decimal(str(movement.rate or 0))
    if not unit_cost and movement.signed_quantity:
        unit_cost = abs(Decimal(str(movement.inventory_cost or 0))) / Decimal(
            movement.signed_quantity
        )
    return unit_cost


def _layer_remaining(layer):
    """A layer's unspent quantity, derived exactly as `ledger_layers` derives it."""
    consumed = sum(
        (
            Decimal(str(row.quantity_consumed or 0))
            for row in StockMovementLayerConsumption.objects.filter(
                source_movement=layer
            )
        ),
        Decimal("0"),
    )
    return Decimal(layer.signed_quantity) - consumed


def credited_layers(credit_note, movements=None):
    """Layers this note put units back onto, and how many. `[(layer, quantity)]`.

    Two shapes are collapsed into one, because the delete has the same problem
    with both:

    * an `ADJUSTMENT_IN` row IS a layer, of its whole signed quantity
    * a `SALE_RETURN` row hands units back to *existing* layers as negative
      consumption slices, which restores exactly that much spendable capacity

    A `PURCHASE_RETURN` credits nothing -- it takes stock away -- so it has
    nothing to check.
    """
    movements = credit_note_movements(credit_note) if movements is None else movements
    credited = {}

    for movement in movements:
        if movement.movement_type == StockMovementTypeChoices.ADJUSTMENT_IN:
            quantity = Decimal(movement.signed_quantity or 0)
            if quantity > 0:
                credited[movement] = credited.get(movement, Decimal("0")) + quantity
            continue

        if movement.movement_type != StockMovementTypeChoices.SALE_RETURN:
            continue

        for row in movement.layer_consumptions.select_related("source_movement"):
            given_back = -Decimal(str(row.quantity_consumed or 0))
            if given_back <= 0 or row.source_movement is None:
                # A positive row is not a give-back, and a slice with no source
                # movement (a pre-ledger purchase lot, or a fallback) has no
                # derivable remaining quantity. The on-hand check below is the
                # backstop for those.
                continue
            layer = row.source_movement
            credited[layer] = credited.get(layer, Decimal("0")) + given_back

    return list(credited.items())


def assert_stock_not_consumed(credit_note, movements=None):
    """Raise unless every layer this note credited still holds what it gave."""
    if credit_note.kind != CreditNoteKindChoices.SALE:
        return

    short = [
        (layer, quantity, remaining)
        for layer, quantity in credited_layers(credit_note, movements=movements)
        for remaining in [_layer_remaining(layer)]
        if remaining < quantity
    ]
    if not short:
        return

    named = ", ".join(
        f"{layer.product.title} ({quantity:g} returned, {remaining:g} still unsold)"
        for layer, quantity, remaining in short
    )
    raise CreditNoteStockConsumed(
        {
            "code": "STOCK-ALREADY-CONSUMED",
            "message": (
                "This credit note cannot be deleted: stock it returned has "
                f"since been sold or used ({named}). Record the movement with a "
                "new document instead, so both stay on the record."
            ),
            "products": [
                {
                    "uid": str(layer.product.uid),
                    "title": layer.product.title,
                    "returned": float(quantity),
                    "remaining": float(remaining),
                }
                for layer, quantity, remaining in short
            ],
        }
    )


# ---------------------------------------------------------------------------
# The inventory undo
# ---------------------------------------------------------------------------


def _on_hand_now(movement):
    """`movement.product`, re-read.

    Each movement carries its own `Product` instance from `select_related`, so
    two movements against one product hold two copies of `quantity` and the
    second write discards the first. The stock-adjustment delete was wrong this
    way until a test caught it.
    """
    product = movement.product
    product.refresh_from_db(fields=["quantity"])
    return product


def _mirror_slices(movement):
    """This movement's own consumption rows, with the signs flipped."""
    return [
        (
            consumption.source_movement or consumption.purchase_item,
            -Decimal(consumption.quantity_consumed or 0),
            Decimal(consumption.unit_cost or 0),
        )
        for consumption in movement.layer_consumptions.all()
        if consumption.quantity_consumed
    ]


def _append_reversal(movement, signed_quantity, layer_slices):
    record_stock_movement(
        company=movement.company,
        product=movement.product,
        date=movement.date,
        movement_type=StockMovementTypeChoices.REVERSAL,
        signed_quantity=signed_quantity,
        rate=movement.rate,
        # Whatever the original did to the asset, undo exactly that. Right for
        # an inbound row (stored positive) and an outbound one (stored negative)
        # alike.
        inventory_cost=-Decimal(movement.inventory_cost or 0),
        warehouse=movement.warehouse,
        created_by=movement.created_by,
        credit_note_item=movement.credit_note_item,
        layer_slices=layer_slices or None,
        note=f"Reversal of movement {movement.id}",
    )


def _take_units_back(movement, layer_slices):
    """Units off hand, layers re-spent. Undoes an inbound row."""
    quantity = abs(int(movement.signed_quantity or 0))
    if not quantity:
        return 0

    product = _on_hand_now(movement)
    on_hand = int(product.quantity or 0)
    if on_hand < quantity:
        raise CreditNoteStockConsumed(
            {
                "code": "STOCK-ALREADY-CONSUMED",
                "message": (
                    "This credit note cannot be deleted: it returned "
                    f"{quantity} of {product.title}, but only {on_hand} remain "
                    "on hand. Record the movement with a new document instead."
                ),
                "products": [
                    {
                        "uid": str(product.uid),
                        "title": product.title,
                        "returned": quantity,
                        "on_hand": on_hand,
                    }
                ],
            }
        )

    product.quantity = on_hand - quantity
    product.save(update_fields=["quantity"])
    _append_reversal(movement, -quantity, layer_slices)
    return quantity


def _put_units_back(movement, layer_slices):
    """Units back on hand, layers un-spent. Undoes an outbound row."""
    quantity = abs(int(movement.signed_quantity or 0))
    if not quantity:
        return 0

    product = _on_hand_now(movement)
    product.quantity = (product.quantity or 0) + quantity
    product.save(update_fields=["quantity"])
    _append_reversal(movement, quantity, layer_slices)
    return quantity


def restore_credit_note_purchase_items(credit_note):
    """Undo the lot quantities a SALE note inflated.

    The posting path adds the returned units to a purchase item as well as to
    `Product.quantity` (`serializers/creditnotes.py:667-670`, `:1457-1460`), and
    **nothing has ever undone it.** `restore_credit_note_quantities` looks the
    lot up through `JournalEntryConnector.purchase_item`, a column no
    credit-note posting path ever writes -- every `connector_data` tuple passes
    `None` in that slot -- so its `layers_restored` is structurally always zero.

    Resolved the way the posting resolved it, from `(product, company, date)`,
    because that is the only record of which lot was chosen: the choice was
    never stored. It can land on a different lot than the original if a purchase
    has been added or its status changed since, which is a narrower failure than
    never undoing it at all.
    """
    from weapi.django_rest.helpers.purchase_item_helpers import (
        get_latest_published_purchase_item,
    )

    if credit_note.kind != CreditNoteKindChoices.SALE:
        return 0

    restored = 0
    for line in credit_note.creditnoteitem_set.select_related("product").order_by("id"):
        product = line.product
        quantity = int(line.quantity or 0)
        if product is None or not quantity:
            continue

        purchase_item = get_latest_published_purchase_item(
            product=product, company=credit_note.company, date=credit_note.date
        )
        if purchase_item is None:
            continue

        purchase_item.quantity = max(0, (purchase_item.quantity or 0) - quantity)
        purchase_item.opening_quantity = max(
            0, (purchase_item.opening_quantity or 0) - quantity
        )
        purchase_item.save(update_fields=["quantity", "opening_quantity"])
        restored += 1

    return restored


def restore_credit_note_inventory(credit_note):
    """Put the stock back. Returns `{"taken_back": …, "put_back": …, "lots": …}`.

    Idempotent: a note that already carries REVERSAL rows has been through here.
    """
    result = {"taken_back": 0, "put_back": 0, "lots": 0}
    movements = credit_note_movements(credit_note)
    if not movements:
        logger.info(
            "void_credit_note: note %s moved no stock", credit_note.pk
        )
        return result

    if _own_reversals(credit_note).exists():
        logger.info(
            "void_credit_note: note %s inventory already restored", credit_note.pk
        )
        return result

    assert_stock_not_consumed(credit_note, movements=movements)

    for movement in movements:
        if movement.movement_type == StockMovementTypeChoices.ADJUSTMENT_IN:
            # Its own layer, spent down to nothing -- taken explicitly rather
            # than through `consumption_slices`, which walks oldest-first and
            # would reprice the stock still on hand.
            result["taken_back"] += _take_units_back(
                movement,
                [
                    (
                        movement,
                        Decimal(abs(int(movement.signed_quantity or 0))),
                        _layer_unit_cost(movement),
                    )
                ],
            )
        elif movement.movement_type == StockMovementTypeChoices.SALE_RETURN:
            result["taken_back"] += _take_units_back(
                movement, _mirror_slices(movement)
            )
        elif movement.movement_type == StockMovementTypeChoices.PURCHASE_RETURN:
            result["put_back"] += _put_units_back(movement, _mirror_slices(movement))

    result["lots"] = restore_credit_note_purchase_items(credit_note)

    logger.info(
        "void_credit_note: note %s took back %s, put back %s, adjusted %s lot(s)",
        credit_note.pk, result["taken_back"], result["put_back"], result["lots"],
    )
    return result


# ---------------------------------------------------------------------------
# The journal undo
# ---------------------------------------------------------------------------


def void_credit_note_postings(credit_note, *, created_by=None):
    """Reverse the journal. Returns `(reversal, party_amount)`.

    `party_amount` is taken from the A/R or A/P leg rather than from
    `credit_note.total`, which is what `_reverse_party_balance` reads and why
    that helper cannot be reused: on the purchase side `total` is decremented by
    every application, so it is the note's *remaining* credit, not the amount the
    posting moved. Keying off the leg also makes the party move conditional in
    the same way the posting was -- the same technique
    `void_purchase_payment_postings` uses.
    """
    entries = list(JournalEntry.objects.filter(credit_note=credit_note))
    if not entries:
        logger.info("void_credit_note: note %s had nothing posted", credit_note.pk)
        return None, Decimal("0.000")

    if JournalEntryConnector.objects.filter(
        journal__in=entries,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
    ).exists():
        logger.info("void_credit_note: note %s is already reversed", credit_note.pk)
        return None, Decimal("0.000")

    originals = list(
        JournalEntryConnector.objects.filter(journal__in=entries)
        .select_related("account")
        .exclude(request_kind=JournalEntryConnectorRequestKindChoices.DELETED)
    )

    is_sale = credit_note.kind == CreditNoteKindChoices.SALE
    control_title = RECEIVABLE_TITLE if is_sale else PAYABLE_TITLE
    party_amount = Decimal("0.000")
    connector_data = []
    for original in originals:
        account = original.account
        if account is None:
            continue
        amount = original.debit if original.debit else original.credit
        if not amount:
            continue

        if account.title == control_title:
            party_amount += Decimal(str(amount))

        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        # Eight elements, not five: credit-note legs are line-attributed through
        # `credit_note_item` at index 7, a slot the payment reversals have no
        # use for. Dropping it would leave the reversal legs unattributable to
        # the line they undo, and the per-line connector queries would not see
        # them.
        connector_data.append(
            (
                account,
                opposite,
                amount,
                account.opening_balance,
                None,
                None,
                None,
                original.credit_note_item,
            )
        )

    if not connector_data:
        logger.info(
            "void_credit_note: note %s had entries but no legs", credit_note.pk
        )
        return None, Decimal("0.000")

    template = entries[0]
    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, template.company_id, "entry_number", "JE"
        ),
        date=credit_note.date,
        amount=template.amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=template.kind,
        is_transaction=True,
        is_journal_entry=True,
        company=template.company,
        credit_note=credit_note,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        customer=credit_note.customer if is_sale else None,
        supplier=credit_note.supplier if not is_sale else None,
        created_by=created_by,
    )

    logger.info(
        "void_credit_note: note %s reversed by entry %s with %s line(s)",
        credit_note.pk, reversal.pk, len(connector_data),
    )
    return reversal, party_amount


def restore_party_balance(credit_note, amount):
    """Put back what the credit took off the customer or supplier.

    Both kinds SUBTRACT at post time -- a sale credit lowers what the customer
    owes, a purchase credit lowers what is owed to the supplier -- so both are
    added back. CREDIT here means "add", not an accounting side: a Customer and a
    Supplier have no account kind for one to be resolved from, which is why this
    cannot go through `action_for_side`.
    """
    party = (
        credit_note.customer
        if credit_note.kind == CreditNoteKindChoices.SALE
        else credit_note.supplier
    )
    if not amount or party is None:
        return Decimal("0.000")

    update_opening_balance(
        party, JournalEntryConnectorKindChoices.CREDIT, amount, 0
    )
    return amount
