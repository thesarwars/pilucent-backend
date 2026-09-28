"""Append-only inventory ledger writer.

`record_stock_movement` is the single entry point every inventory-mutating flow
calls **right after** it has changed on-hand quantity. It snapshots the running
balances so the Inventory Valuation Detail report is a straight read:

The ledger stores only the immutable *facts* of each movement (signed quantity,
rate, signed ``inventory_cost``). Running quantity-on-hand and asset value are
**derived at read time** by the report, cumulating these in date order — so a
backdated document can never corrupt a running balance. ``current_inventory_asset_value``
remains available as a reconciliation cross-check.

For an outbound sale, pass ``layer_slices`` (the FIFO ``deduction_details``);
each slice is persisted as a ``StockMovementLayerConsumption`` so per-line COGS
is attributable per lot — the consumed-quantity the journal never stored.

Call inside the caller's ``transaction.atomic`` so the ledger row commits/rolls
back with its source document.
"""

import logging
from datetime import date as date_cls
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce

from purchaseio.choices import PurchaseItemStatus, PurchaseStatus
from purchaseio.models import PurchaseItem

from stockio.choices import StockMovementTypeChoices
from stockio.models import StockMovement, StockMovementLayerConsumption

logger = logging.getLogger(__name__)

# The purchase statuses / kinds that count as stock-on-hand cost layers — must
# stay in lock-step with fifo_product_deduction so value ties to what FIFO relieves.
_VALID_PURCHASE_STATUSES = [
    PurchaseStatus.OPEN,
    PurchaseStatus.ACCEPTED,
    PurchaseStatus.CLOSED,
    PurchaseStatus.COMPLETED,
]


def current_inventory_asset_value(product):
    """FIFO asset value of the stock currently on hand for ``product``."""
    agg = (
        PurchaseItem.objects.filter(
            product=product,
            status=PurchaseItemStatus.PUBLISHED,
            purchase__status__in=_VALID_PURCHASE_STATUSES,
            quantity__gt=0,
        )
        .filter(
            Q(purchase__is_bill=True)
            | Q(purchase__is_cheque=True)
            | Q(purchase__is_via_expense=True)
        )
        .aggregate(
            value=Coalesce(
                Sum(
                    F("quantity") * F("purchase_price"),
                    output_field=DecimalField(max_digits=19, decimal_places=3),
                ),
                Decimal("0"),
                output_field=DecimalField(max_digits=19, decimal_places=3),
            )
        )
    )
    return agg["value"] or Decimal("0")


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _consumption_row(company, movement, lot, quantity, price):
    """One consumption row, whichever kind of layer it drew from.

    A slice's first element used to be a `PurchaseItem` or None. It may now also
    be a `StockMovement` -- an opening balance, a customer return, a positive
    adjustment -- because those carry cost too and a purchase is not the only
    thing that can be a layer.

    Where the slice names a purchase item, its own PURCHASE movement is recorded
    as the source as well when one exists, so both views of the same fact agree
    and the ledger can answer what is left on that layer without consulting
    `PurchaseItem.quantity`.
    """
    purchase_item = source_movement = None
    if isinstance(lot, StockMovement):
        source_movement = lot
        purchase_item = lot.purchase_item
    elif lot is not None:
        purchase_item = lot
        source_movement = (
            StockMovement.objects.filter(
                purchase_item=lot, signed_quantity__gt=0
            )
            .order_by("date", "id")
            .first()
        )

    return StockMovementLayerConsumption(
        company=company,
        movement=movement,
        purchase_item=purchase_item,
        source_movement=source_movement,
        quantity_consumed=_as_decimal(quantity),
        unit_cost=_as_decimal(price),
        cost_amount=_as_decimal(quantity) * _as_decimal(price),
        is_fallback=lot is None,
    )


def record_stock_movement(
    *,
    company,
    product,
    date,
    movement_type,
    signed_quantity,
    rate=None,
    inventory_cost=None,
    warehouse=None,
    created_by=None,
    purchase_item=None,
    sale_item=None,
    credit_note_item=None,
    stock_adjustment_item=None,
    note=None,
    layer_slices=None,
):
    """Append one ``StockMovement`` (+ layer-consumption rows) for a stock event.

    ``signed_quantity`` is + inbound / - outbound. ``inventory_cost`` is the
    signed cost impact; if omitted it's derived from ``layer_slices`` (outbound
    COGS, negative) or ``signed_quantity * rate`` (inbound). ``layer_slices`` is
    the FIFO ``[(purchase_item|None, qty, unit_price), ...]``. A zero-quantity
    movement with no layers is a no-op (returns None) so reconciliation stays
    exact. Running balances are NOT stored — the report derives them in date order.
    """
    signed_quantity = int(signed_quantity)
    if signed_quantity == 0 and not layer_slices:
        return None

    if inventory_cost is None:
        if layer_slices:
            cogs = sum(
                (_as_decimal(qty) * _as_decimal(price) for _pi, qty, price in layer_slices),
                Decimal("0"),
            )
            inventory_cost = -cogs  # outbound: asset falls
        elif rate is not None:
            inventory_cost = Decimal(str(signed_quantity)) * _as_decimal(rate)
        else:
            inventory_cost = Decimal("0")
    inventory_cost = _as_decimal(inventory_cost)

    # Own savepoint: a caller invokes this best-effort inside its posting
    # transaction. Without the nested atomic, a DB error here would poison the
    # outer transaction (the caller's later ORM ops would raise
    # TransactionManagementError even though the caller caught us). The savepoint
    # confines any failure to the ledger write and re-raises for the caller to log.
    with transaction.atomic():
        movement = StockMovement.objects.create(
            company=company,
            product=product,
            date=date,
            movement_type=movement_type,
            signed_quantity=signed_quantity,
            rate=_as_decimal(rate) if rate is not None else None,
            inventory_cost=inventory_cost,
            warehouse=warehouse,
            created_by=created_by,
            purchase_item=purchase_item,
            sale_item=sale_item,
            credit_note_item=credit_note_item,
            stock_adjustment_item=stock_adjustment_item,
            note=note,
        )
        if layer_slices:
            StockMovementLayerConsumption.objects.bulk_create(
                [
                    _consumption_row(company, movement, lot, qty, price)
                    for lot, qty, price in layer_slices
                ]
            )

    return movement


def record_opening_stock(product, rate=None, created_by=None):
    """Record a product's starting on-hand quantity as an OPENING movement.

    Returns the movement, or None when there is nothing to record.

    Creating a product with a quantity states a fact about inventory, and until
    now nothing wrote it down. `OPENING` was produced by exactly one thing --
    `manage.py seed_stock_opening_movements`, a one-shot backfill -- so every
    product created after that command ran has no opening row at all.

    The ledger is what the valuation reports cumulate, so a product opened with
    100 units and then sold 10 read as quantity -10 and asset value -100: the
    sale was the only row in its ledger. Meanwhile `Product.quantity` said 90
    and the general ledger said 900. Three figures, no two agreeing, on an item
    nobody had done anything unusual with.

    Idempotent by design: an existing OPENING row for the product is left alone,
    so re-running against a product the backfill already covered does not open
    it twice.
    """
    from stockio.choices import StockMovementTypeChoices

    quantity = int(product.quantity or 0)
    if quantity <= 0:
        return None

    if not product.tracks_stock():
        logger.info(
            "stock ledger: %r is a %s, not stocked -- no opening movement",
            product.title, product.kind,
        )
        return None

    if StockMovement.objects.filter(
        product=product, movement_type=StockMovementTypeChoices.OPENING
    ).exists():
        logger.info(
            "stock ledger: product %s already has an opening movement", product.pk
        )
        return None

    unit_cost = Decimal(str(rate or 0))
    return record_stock_movement(
        company=product.company,
        product=product,
        date=product.date or date_cls.today(),
        movement_type=StockMovementTypeChoices.OPENING,
        signed_quantity=quantity,
        rate=unit_cost,
        inventory_cost=Decimal(quantity) * unit_cost,
        created_by=created_by,
        note="Opening on-hand quantity recorded at product creation.",
    )



def record_adjustment_stock(item, *, unit_cost=None, created_by=None, note=None):
    """Append the movement for one stock-adjustment line.

    A stock adjustment is the one document whose entire purpose is to move
    inventory, and it was the one moving it with no ledger row at all -- writing
    `Product.quantity` and the journal legs and nothing here.

    Written UP is `ADJUSTMENT_IN`: costed units with no purchase behind them, so
    it becomes a cost layer in its own right at `unit_cost`. That is why
    `INBOUND_TYPES` names it -- a purchase is not the only thing that can carry
    cost. Written DOWN is `ADJUSTMENT_OUT`, relieving the oldest layers first
    like any other outbound; units no layer accounts for become a fallback slice
    rather than vanishing, because shrinkage is exactly the case where on-hand
    and the layers are already known to disagree.

    Best-effort: a ledger failure must not take the adjustment down with it.
    """
    from stockio.choices import StockAdjustmentItemKindChoices

    product = getattr(item, "product", None)
    quantity = int(getattr(item, "quantity", 0) or 0)
    if product is None or not quantity:
        return None

    adjustment = item.stock_adjustment
    addition = item.kind == StockAdjustmentItemKindChoices.ADDITION

    try:
        if addition:
            return record_stock_movement(
                company=adjustment.company,
                product=product,
                date=adjustment.date,
                movement_type=StockMovementTypeChoices.ADJUSTMENT_IN,
                signed_quantity=quantity,
                rate=unit_cost,
                created_by=created_by,
                stock_adjustment_item=item,
                note=note,
            )

        slices, _unplaced = consumption_slices(
            product, quantity, fallback_rate=unit_cost or 0
        )
        return record_stock_movement(
            company=adjustment.company,
            product=product,
            date=adjustment.date,
            movement_type=StockMovementTypeChoices.ADJUSTMENT_OUT,
            signed_quantity=-quantity,
            rate=unit_cost,
            layer_slices=slices,
            created_by=created_by,
            stock_adjustment_item=item,
            note=note,
        )
    except Exception:
        logger.exception(
            "stock ledger: failed to record adjustment item %s for product %s",
            getattr(item, "pk", None), getattr(product, "pk", None),
        )
        return None


# The movement types that ADD costed units, and are therefore cost layers.
#
# REVERSAL is deliberately NOT one of them. A reversal compensates one specific
# earlier movement, and it expresses that by carrying negative layer slices --
# giving the units back to the exact layer they came from, at the cost they were
# taken at. Counting the reversal row as a layer as well would return the same
# stock twice, and at the wrong price: its `rate` is the sale price, not a cost.
#
# SALE_RETURN is out for exactly that reason, and used to be in. It carries
# reversal slices now (see `reversal_slices`), so counting it as a layer as well
# double-counted the returned stock. Measured before the change: buy 10 at 4,
# sell 3, return 1 left `ledger_on_hand` reporting 8 units while the layers
# summed to 7 -- one of them a SALE_RETURN priced at the SALE price of 10. A
# return that cannot be traced to any consumption is recorded as ADJUSTMENT_IN
# instead, which IS a layer, because those units genuinely have no source here.
INBOUND_TYPES = ("OPENING", "PURCHASE", "ADJUSTMENT_IN")


def reversal_slices(product, quantity):
    """Negative slices handing `quantity` units back to the layers they left.

    Returns `(slices, unplaced)`. Each slice is `(lot, -qty, unit_cost)` in the
    shape `record_stock_movement` already takes, so a return is expressed as the
    arithmetic inverse of the sale that consumed the stock -- the same lot, the
    same cost. `unplaced` is what could not be attributed to any consumption.

    **Most-recently-consumed first.** A refund receipt carries no link back to
    the sale it reverses -- `Sale.refund_from` is commented out in the model --
    so the original document cannot be named. Walking consumption newest-first
    is the closest available reading of "put these units back where they came
    from", and it is exact whenever the return follows the sale, which is the
    ordinary case.

    Consumption is netted per source layer, so returning the same units twice
    cannot un-consume more than was ever taken: an earlier reversal's negative
    rows reduce the pool this one can draw from.

    `unplaced` is the honest remainder -- a refund against a sale that predates
    this ledger has nothing to give back to. The caller records those units
    separately rather than inventing a layer here.
    """
    quantity = Decimal(str(int(quantity or 0)))
    if quantity <= 0:
        return [], 0

    rows = (
        StockMovementLayerConsumption.objects.filter(movement__product=product)
        .select_related("movement", "source_movement", "purchase_item")
        .order_by("-movement__date", "-movement_id", "-id")
    )

    # Net per source layer, in most-recently-consumed order.
    net, order = {}, []
    for row in rows:
        key = (
            ("movement", row.source_movement_id)
            if row.source_movement_id
            else ("purchase_item", row.purchase_item_id)
        )
        if key not in net:
            net[key] = {
                "quantity": Decimal("0"),
                "lot": row.source_movement or row.purchase_item,
                "unit_cost": _as_decimal(row.unit_cost),
            }
            order.append(key)
        net[key]["quantity"] += _as_decimal(row.quantity_consumed)

    slices = []
    remaining = quantity
    for key in order:
        if remaining <= 0:
            break
        entry = net[key]
        available = entry["quantity"]
        if available <= 0:
            continue
        take = min(available, remaining)
        slices.append((entry["lot"], -take, entry["unit_cost"]))
        remaining -= take

    return slices, int(remaining)


def consumption_slices(product, quantity, *, fallback_rate=None, prefer_movement=None):
    """Positive slices taking `quantity` units out of the oldest layers first.

    The outbound twin of `reversal_slices`, and the mirror of what
    `fifo_product_deduction` computes -- **without its mutations.** That matters
    for the flows that decrement on-hand themselves: a purchase credit note calls
    `update_quantity` and then needs to say which layers the goods left from, and
    calling the FIFO helper for that would deduct the same units a second time.

    Returns `(slices, unplaced)`. When `fallback_rate` is given, units no layer
    accounts for become one slice with no lot -- persisted as `is_fallback`, the
    same admission `fifo_product_deduction` makes -- and `unplaced` is 0. Without
    it, they are reported instead of priced, because inventing a cost is worse
    than recording that we could not attribute one.

    `prefer_movement` puts one layer at the front of the walk. Undoing a purchase
    line should take the units off the layer THAT line created, not off whatever
    happens to be oldest -- otherwise amending a bill silently reprices the
    stock still on hand. It is a preference and not a restriction: if the line's
    own layer has already been sold down, the remainder comes from the rest in
    the ordinary order, and the invariant holds either way.
    """
    quantity = Decimal(str(int(quantity or 0)))
    if quantity <= 0:
        return [], 0

    layers = ledger_layers(product)
    if prefer_movement is not None:
        layers.sort(key=lambda row: row[0].pk != getattr(prefer_movement, "pk", None))

    slices = []
    remaining = quantity
    for movement, available, unit_cost in layers:
        if remaining <= 0:
            break
        take = min(_as_decimal(available), remaining)
        if take <= 0:
            continue
        # The lot where there is one, so callers recording a `purchase_item` FK
        # keep getting what they always got.
        slices.append((movement.purchase_item or movement, take, unit_cost))
        remaining -= take

    if remaining > 0 and fallback_rate is not None:
        slices.append((None, remaining, _as_decimal(fallback_rate)))
        remaining = Decimal("0")

    return slices, int(remaining)


def ledger_layers(product, as_of=None):
    """Cost layers still available for `product`, oldest first.

    Returns `[(movement, remaining_quantity, unit_cost)]`.

    This is the ledger's answer to "what stock do we hold and what did it cost",
    and it differs from the existing one in what it is willing to call a layer.
    `fifo_product_deduction` walks `PurchaseItem` rows, so a purchase is the only
    thing that can carry cost -- opening stock, a customer return and a positive
    adjustment all add costed units and none of them is a purchase. A product
    opened with 100 units therefore had no layer at all, and selling from it fell
    through to a fallback price of zero: revenue recognised with no cost against
    it, gross margin reading 100%.

    Remaining quantity is derived, not stored: a layer's signed quantity less
    everything consumed against it. That is only answerable because consumption
    now records `source_movement`; before, it named a `purchase_item`, so a
    layer's remaining life lived in `PurchaseItem.quantity` -- a mutable column
    on a document, which is why it could disagree with the ledger.

    Ordering is `(date, id)`: FIFO by the date the stock arrived, with the row
    id breaking ties so the order is total and repeatable.
    """
    from django.db.models import Sum

    queryset = StockMovement.objects.filter(
        company=product.company_id, product=product, movement_type__in=INBOUND_TYPES
    ).filter(signed_quantity__gt=0)
    if as_of:
        queryset = queryset.filter(date__lte=as_of)

    consumed = {
        row["source_movement"]: row["used"]
        for row in StockMovementLayerConsumption.objects.filter(
            source_movement__product=product
        )
        .values("source_movement")
        .annotate(used=Coalesce(Sum("quantity_consumed"), Decimal("0")))
    }

    layers = []
    for movement in queryset.order_by("date", "id"):
        used = Decimal(str(consumed.get(movement.pk, 0)))
        remaining = Decimal(movement.signed_quantity) - used
        if remaining <= 0:
            continue
        # Prefer the movement's own rate; fall back to its cost per unit, which
        # is what a purchase records when the rate column is not set.
        unit_cost = Decimal(str(movement.rate or 0))
        if not unit_cost and movement.signed_quantity:
            unit_cost = abs(
                Decimal(str(movement.inventory_cost or 0))
            ) / Decimal(movement.signed_quantity)
        layers.append((movement, remaining, unit_cost))
    return layers


def ledger_on_hand(product, as_of=None):
    """On-hand quantity for `product` as the ledger sees it.

    Every movement, not only the layers -- outbound rows are negative, so this
    is the straight cumulative sum. Exposed so the ledger's figure can be
    compared with `Product.quantity` and with what the layers say is left.
    """
    from django.db.models import Sum

    queryset = StockMovement.objects.filter(company=product.company_id, product=product)
    if as_of:
        queryset = queryset.filter(date__lte=as_of)
    total = queryset.aggregate(
        n=Coalesce(Sum("signed_quantity"), 0)
    )["n"]
    return int(total or 0)
