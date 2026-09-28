"""Undoing a stock adjustment: the units, the cost layers, the legs, the balances.

`DELETE /we/stock/adjustment/{uid}` set the document's status to REMOVED and did
nothing else, so the one document whose entire purpose is to move inventory could
be deleted without moving any of it back. The units stayed on hand, the layers
stayed created or spent, both journal legs stayed PUBLISHED -- and the adjustment
account went on carrying a write-up or write-down for a document that no longer
existed.

Two things make this the hardest of the five delete paths.

**The item rows cannot be trusted to say what posted.** `PATCH` on an adjustment
rewrites `StockAdjustmentItem` -- quantity, kind, even the product -- and touches
neither `Product.quantity`, nor the ledger, nor the journal
(`serializers/stock.py:349-400`). Edit an adjustment and its lines stop
describing the movement it made. So everything here is driven off `StockMovement`,
which is append-only and therefore still true.

**Returning stock is not the same as adding stock.** Cost layers are read off
this ledger, and a layer's remaining quantity is its inbound signed quantity less
everything consumed against it. Handing units back to on-hand without also
undoing the *attribution* leaves the layer they came from looking spent -- FIFO
skips it and sells the same stock a second time at the next layer's cost, or at
the zero fallback. So a reversal carries negative slices against the exact layer
it drew from, the way `sale_posting._record_reversal_movement` has done for sales
since the FIFO ledger landed.

**The order of the two passes is load-bearing.** One adjustment can write a
product up and another (or the same product) down, and the write-down's
`consumption_slices` walk includes the write-up's brand-new layer. Reverse the
`ADJUSTMENT_IN` first and its layer is still showing as consumed, so there is
nothing left to withdraw: `record_stock_movement` returns None, the journal moves
by the full amount and `Product.quantity` moves by nothing. Every
`ADJUSTMENT_OUT` is reversed first, which releases that internal consumption,
and only then is each `ADJUSTMENT_IN` withdrawn.

**Which is why this one can refuse.** If a *different* document has already sold
or consumed layers this adjustment created, there is no honest reversal: the
units are gone. Taking them anyway either trips the `PositiveIntegerField` check
on `Product.quantity` or -- worse, because it is silent -- leaves a full
amount-based journal reversal beside a partial quantity-based one. It refuses and
names the products, the same shape as the reconciled guard.
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

from journalio.choices import (
    JournalEntryConnectorRequestKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector

from stockio.choices import StockMovementTypeChoices
from stockio.django_rest.services.stock_movement import record_stock_movement
from stockio.models import StockMovement, StockMovementLayerConsumption

logger = logging.getLogger(__name__)


ADJUSTMENT_TYPES = (
    StockMovementTypeChoices.ADJUSTMENT_IN,
    StockMovementTypeChoices.ADJUSTMENT_OUT,
)


class AdjustmentStockConsumed(ValidationError):
    """409-shaped refusal: another document is holding stock this one created."""


def adjustment_movements(adjustment):
    """This adjustment's own IN/OUT rows, oldest first.

    Filtered by `movement_type` rather than by the FK alone, because the
    REVERSAL rows written below carry `stock_adjustment_item` too -- that is
    deliberate, it is what makes a reversed adjustment recognisable as reversed,
    and it is also what would make a naive FK query reverse its own reversals.
    """
    return list(
        StockMovement.objects.filter(
            stock_adjustment_item__stock_adjustment=adjustment,
            movement_type__in=ADJUSTMENT_TYPES,
        )
        .select_related("product", "stock_adjustment_item")
        .order_by("id")
    )


def _own_reversals(adjustment):
    return StockMovement.objects.filter(
        stock_adjustment_item__stock_adjustment=adjustment,
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


def externally_consumed_layers(adjustment, movements=None):
    """Layers this adjustment created that some **other** document has drawn from.

    Returns `[(movement, quantity_taken)]`.

    Consumption by this adjustment's own lines does not count. A single document
    can write a product up and then down, and the write-down legitimately draws
    on the write-up's layer -- reversing the `ADJUSTMENT_OUT` first gives those
    units straight back, so they were never really gone. Only a consumer outside
    this document represents stock that has actually left.
    """
    movements = adjustment_movements(adjustment) if movements is None else movements
    incoming = [
        movement
        for movement in movements
        if movement.movement_type == StockMovementTypeChoices.ADJUSTMENT_IN
    ]
    if not incoming:
        return []

    ours = {movement.pk for movement in movements}
    ours |= set(_own_reversals(adjustment).values_list("pk", flat=True))

    taken = {}
    rows = StockMovementLayerConsumption.objects.filter(
        source_movement__in=incoming
    ).exclude(movement_id__in=ours)
    for row in rows:
        quantity = Decimal(str(row.quantity_consumed or 0))
        if not quantity:
            continue
        taken[row.source_movement_id] = taken.get(
            row.source_movement_id, Decimal("0")
        ) + quantity

    return [
        (movement, taken[movement.pk])
        for movement in incoming
        if taken.get(movement.pk, Decimal("0")) > 0
    ]


def assert_stock_not_consumed(adjustment, movements=None):
    """Raise unless every layer this adjustment created is still whole."""
    consumed = externally_consumed_layers(adjustment, movements=movements)
    if not consumed:
        return

    named = ", ".join(
        f"{movement.product.title} ({quantity:g} of {movement.signed_quantity})"
        for movement, quantity in consumed
    )
    raise AdjustmentStockConsumed(
        {
            "code": "STOCK-ALREADY-CONSUMED",
            "message": (
                "This adjustment cannot be deleted: stock it added has since "
                f"been used by other documents ({named}). Write the stock back "
                "down with a new adjustment instead, so both movements stay on "
                "the record."
            ),
            "products": [
                {
                    "uid": str(movement.product.uid),
                    "title": movement.product.title,
                    "added": movement.signed_quantity,
                    "consumed": float(quantity),
                }
                for movement, quantity in consumed
            ],
        }
    )


def _on_hand_now(movement):
    """`movement.product`, re-read.

    Each movement carries its OWN `Product` instance from `select_related`, so
    two movements against one product hold two objects with two copies of
    `quantity`. Read the cached one and the second write silently discards the
    first: a mixed adjustment reversed 4 units back on hand and then withdrew 10
    from a Python object that still believed there were 6.
    """
    product = movement.product
    product.refresh_from_db(fields=["quantity"])
    return product


def _return_units(movement):
    """Undo one `ADJUSTMENT_OUT`: units back on hand, layers un-spent.

    The mirror of `sale_posting._record_reversal_movement` -- negative slices
    against the same lots at the same cost, so the layer is credited back
    exactly what this movement took.
    """
    quantity = abs(int(movement.signed_quantity or 0))
    if not quantity:
        return 0

    giving_back = [
        (
            consumption.source_movement or consumption.purchase_item,
            -Decimal(consumption.quantity_consumed or 0),
            Decimal(consumption.unit_cost or 0),
        )
        for consumption in movement.layer_consumptions.all()
        if consumption.quantity_consumed
    ]

    product = _on_hand_now(movement)
    product.quantity = (product.quantity or 0) + quantity
    product.save(update_fields=["quantity"])

    record_stock_movement(
        company=movement.company,
        product=product,
        date=movement.date,
        movement_type=StockMovementTypeChoices.REVERSAL,
        signed_quantity=quantity,
        rate=movement.rate,
        # An OUT stored a negative `inventory_cost` (the asset fell); the
        # reversal is its arithmetic inverse. The same expression is right for
        # an IN, where the stored cost is positive.
        inventory_cost=-Decimal(movement.inventory_cost or 0),
        warehouse=movement.warehouse,
        created_by=movement.created_by,
        stock_adjustment_item=movement.stock_adjustment_item,
        layer_slices=giving_back or None,
        note=f"Reversal of movement {movement.id}",
    )
    return quantity


def _withdraw_units(movement):
    """Undo one `ADJUSTMENT_IN`: units off hand, the layer it created spent.

    Consumes the layer explicitly rather than through `consumption_slices`,
    which walks oldest-first and would take the units off whatever layer happens
    to be older -- silently repricing the stock still on hand. This one line
    created this one layer, and this is the layer that has to go.
    """
    quantity = int(movement.signed_quantity or 0)
    if quantity <= 0:
        return 0

    product = _on_hand_now(movement)
    on_hand = int(product.quantity or 0)
    if on_hand < quantity:
        # Reachable without any layer consumption: a flow that decremented
        # on-hand without recording against this layer, or an adjustment whose
        # `record_adjustment_stock` failed (it is best-effort) after the
        # serializer had already moved the quantity. Refuse rather than let
        # `Product.quantity`'s PositiveIntegerField check surface as a 500.
        raise AdjustmentStockConsumed(
            {
                "code": "STOCK-ALREADY-CONSUMED",
                "message": (
                    "This adjustment cannot be deleted: it added "
                    f"{quantity} of {product.title}, but only {on_hand} "
                    "remain on hand. Write the stock back down with a new "
                    "adjustment instead."
                ),
                "products": [
                    {
                        "uid": str(product.uid),
                        "title": product.title,
                        "added": quantity,
                        "on_hand": on_hand,
                    }
                ],
            }
        )

    product.quantity = on_hand - quantity
    product.save(update_fields=["quantity"])

    record_stock_movement(
        company=movement.company,
        product=product,
        date=movement.date,
        movement_type=StockMovementTypeChoices.REVERSAL,
        signed_quantity=-quantity,
        rate=movement.rate,
        inventory_cost=-Decimal(movement.inventory_cost or 0),
        warehouse=movement.warehouse,
        created_by=movement.created_by,
        stock_adjustment_item=movement.stock_adjustment_item,
        layer_slices=[(movement, Decimal(quantity), _layer_unit_cost(movement))],
        note=f"Reversal of movement {movement.id}",
    )
    return quantity


def restore_stock_adjustment_inventory(adjustment):
    """Put the inventory back. Returns `{"returned": …, "withdrawn": …}`.

    Two passes, and the order between them is the whole point -- see the module
    docstring. Idempotent: an adjustment that already carries REVERSAL rows has
    been through here, and running it again would return the units twice.
    """
    result = {"returned": 0, "withdrawn": 0}
    movements = adjustment_movements(adjustment)
    if not movements:
        logger.info(
            "void_stock_adjustment: adjustment %s moved no stock", adjustment.pk
        )
        return result

    if _own_reversals(adjustment).exists():
        logger.info(
            "void_stock_adjustment: adjustment %s inventory already restored",
            adjustment.pk,
        )
        return result

    assert_stock_not_consumed(adjustment, movements=movements)

    # Pass A: every write-down, releasing the layers it consumed -- including
    # any layer this same document created in Pass B's rows.
    for movement in movements:
        if movement.movement_type == StockMovementTypeChoices.ADJUSTMENT_OUT:
            result["returned"] += _return_units(movement)

    # Pass B: every write-up, now that its layer is whole again.
    for movement in movements:
        if movement.movement_type == StockMovementTypeChoices.ADJUSTMENT_IN:
            result["withdrawn"] += _withdraw_units(movement)

    logger.info(
        "void_stock_adjustment: adjustment %s returned %s and withdrew %s unit(s)",
        adjustment.pk, result["returned"], result["withdrawn"],
    )
    return result


def void_stock_adjustment_postings(adjustment, *, created_by=None):
    """Reverse the journal. Returns the reversing entry, or None.

    The original entry is left alone and a second one is posted with the sides
    flipped, marked DELETED, so the pair nets to zero and a deleted adjustment
    can still be explained afterwards.

    Dated to the adjustment, not to today: `create_journal_entry_connector`
    takes the entry's own date for its legs, so an adjustment made in January
    and deleted in September reverses in January -- where the original sits in
    the register, and inside whatever period the original belongs to.
    """
    entries = list(JournalEntry.objects.filter(stock_adjustment=adjustment))
    if not entries:
        logger.info(
            "void_stock_adjustment: adjustment %s had nothing posted", adjustment.pk
        )
        return None

    if JournalEntryConnector.objects.filter(
        journal__in=entries,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
    ).exists():
        logger.info(
            "void_stock_adjustment: adjustment %s is already reversed", adjustment.pk
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

        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        connector_data.append(
            (account, opposite, amount, account.opening_balance, None)
        )

    if not connector_data:
        logger.info(
            "void_stock_adjustment: adjustment %s had entries but no legs",
            adjustment.pk,
        )
        return None

    template = entries[0]
    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, template.company_id, "entry_number", "JE"
        ),
        date=adjustment.date,
        amount=template.amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=template.kind,
        is_transaction=True,
        is_journal_entry=True,
        company=template.company,
        stock_adjustment=adjustment,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        created_by=created_by,
    )

    logger.info(
        "void_stock_adjustment: adjustment %s reversed by entry %s with %s line(s)",
        adjustment.pk, reversal.pk, len(connector_data),
    )
    return reversal
