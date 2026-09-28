import logging
from decimal import Decimal
from purchaseio.models import PurchaseItem
from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
from django.db.models import Q
from common.django_rest.helpers.quantity_helpers import update_quantity

logger = logging.getLogger(__name__)


def as_purchase_item(layer_source):
    """The PurchaseItem behind a layer, or None.

    A FIFO slice's first element used to be a PurchaseItem or None, and several
    callers assign it straight to a `purchase_item` foreign key. It may now also
    be a StockMovement -- opening stock, a customer return, a positive
    adjustment -- so those assignments go through here.
    """
    return layer_source if isinstance(layer_source, PurchaseItem) else None


def fifo_product_deduction(product, quantity_to_deduct):
    """Consume `quantity_to_deduct` from the oldest cost layers first.

    Returns `(remaining, deduction_details, purchase_price_groups)` exactly as
    before. `deduction_details` is `[(layer_source, quantity, unit_cost)]`, and
    `layer_source` is still the PurchaseItem where the stock came from a
    purchase -- so every existing caller is unaffected. It is a StockMovement
    where the stock came from anything else, which is the point: opening stock,
    customer returns and positive adjustments all add costed units, and none of
    them is a purchase. Use `as_purchase_item()` before assigning it to a FK.

    Layers come from the stock ledger rather than from a PurchaseItem query.
    Under the old rule a purchase was the only thing that could carry cost, so a
    product opened with 100 units had no layer at all and selling from it fell
    through to a fallback unit cost of zero -- revenue recognised with no cost
    against it, gross margin reading 100%, and Inventory Asset never moving.

    `PurchaseItem.quantity` is still decremented for the layers that have one.
    The ledger is what decides which layers and at what cost, but that column is
    read in several other places, so it is kept in step rather than left to rot.
    Retiring it is a separate change.

    If the ledger has no layers at all for a product that does have purchase
    lots, this falls back to the old walk and says so. That is the
    un-backfilled case: `manage.py backfill_stock_ledger_layers` seeds lots
    bought before the ledger existed, and until it runs, trusting an empty
    ledger would sell real stock at zero cost.
    """
    from stockio.django_rest.services.stock_movement import ledger_layers

    layers = ledger_layers(product)
    if not layers and _has_purchase_lots(product):
        logger.warning(
            "fifo: product %s has purchase lots but no ledger layers -- falling "
            "back to the lot walk. Run backfill_stock_ledger_layers.",
            getattr(product, "pk", None),
        )
        return _legacy_lot_deduction(product, quantity_to_deduct)

    remaining_quantity = int(quantity_to_deduct or 0)
    deduction_details = []
    purchase_price_groups = {}
    total_deducted = 0

    for movement, available, unit_cost in layers:
        if remaining_quantity <= 0:
            break
        take = min(int(available), remaining_quantity)
        if take <= 0:
            continue

        # Report the lot where there is one, so callers that record a
        # purchase_item FK keep getting what they always got.
        source = movement.purchase_item or movement
        deduction_details.append((source, take, unit_cost))
        purchase_price_groups[unit_cost] = (
            purchase_price_groups.get(unit_cost, 0) + take
        )

        lot = movement.purchase_item
        if lot is not None:
            lot.quantity = max(int(lot.quantity or 0) - take, 0)
            lot.save(update_fields=["quantity"])

        remaining_quantity -= take
        total_deducted += take

    if total_deducted > 0:
        update_quantity(product, "deduction", total_deducted, 0)

    # Stock on hand that no layer accounts for. Kept because on-hand can exceed
    # what the ledger explains, and refusing to sell it would be a worse answer
    # than selling it at the product's own cost.
    if remaining_quantity > 0 and (product.quantity or 0) > 0:
        take = min(remaining_quantity, int(product.quantity))
        if take > 0:
            product.quantity -= take
            product.save(update_fields=["quantity"])
            additional_cost = product.productadditionalcost_set.first()
            price = additional_cost.amount if additional_cost else 0
            deduction_details.append((None, take, price))
            purchase_price_groups[price] = purchase_price_groups.get(price, 0) + take
            remaining_quantity -= take

    return remaining_quantity, deduction_details, purchase_price_groups


def _has_purchase_lots(product):
    return _layer_lots(product).exists()


def _layer_lots(product):
    """The PurchaseItem rows the old rule treated as layers."""
    return (
        PurchaseItem.objects.filter(
            product=product,
            status=PurchaseItemStatus.PUBLISHED,
            purchase__status__in=[
                PurchaseStatus.OPEN,
                PurchaseStatus.ACCEPTED,
                PurchaseStatus.CLOSED,
                PurchaseStatus.COMPLETED,
            ],
            quantity__gt=0,
        )
        .order_by("created_at")
        .filter(
            Q(purchase__is_bill=True)
            | Q(purchase__is_cheque=True)
            | Q(purchase__is_via_expense=True)
        )
    )


def _legacy_lot_deduction(product, quantity_to_deduct):
    """The pre-ledger walk, kept for tenants whose lots are not yet seeded."""
    remaining_quantity = quantity_to_deduct
    deduction_details = []
    purchase_price_groups = {}
    total_deducted = 0

    for purchase_item in _layer_lots(product):
        if remaining_quantity <= 0:
            break
        deduct = min(purchase_item.quantity, remaining_quantity)
        if deduct <= 0:
            continue
        purchase_item.quantity -= deduct
        purchase_item.save()
        total_deducted += deduct
        remaining_quantity -= deduct
        deduction_details.append((purchase_item, deduct, purchase_item.purchase_price))
        price = purchase_item.purchase_price or 0
        purchase_price_groups[price] = purchase_price_groups.get(price, 0) + deduct

    if total_deducted > 0:
        update_quantity(product, "deduction", total_deducted, 0)

    if remaining_quantity > 0 and product.quantity > 0:
        deduct = min(remaining_quantity, product.quantity)
        if deduct > 0:
            product.quantity -= deduct
            product.save()
            additional_cost = product.productadditionalcost_set.first()
            price = additional_cost.amount if additional_cost else 0
            deduction_details.append((None, deduct, price))
            purchase_price_groups[price] = purchase_price_groups.get(price, 0) + deduct
            remaining_quantity -= deduct

    return remaining_quantity, deduction_details, purchase_price_groups


def fifo_cost_calculation(product, quantity):
    
    valid_statuses = [
        PurchaseStatus.OPEN,
        PurchaseStatus.ACCEPTED,
        PurchaseStatus.CLOSED,
        PurchaseStatus.COMPLETED,
    ]

    purchase_items = (
        PurchaseItem.objects.filter(
            product=product,
            status=PurchaseItemStatus.PUBLISHED,
            purchase__status__in=valid_statuses,
        )
        .order_by("created_at")
        .filter(
            Q(purchase__is_bill=True)
            | Q(purchase__is_cheque=True)
            | Q(purchase__is_via_expense=True)
        )
    )

    remaining_quantity = quantity
    purchase_price_groups = {}
    total_cost = Decimal("0")

    for purchase_item in purchase_items:
        if remaining_quantity <= 0:
            break

        price = purchase_item.purchase_price or 0

        original_qty = purchase_item.quantity if purchase_item.quantity > 0 else 1
        qty_from_this_item = min(original_qty, remaining_quantity)

        if price not in purchase_price_groups:
            purchase_price_groups[price] = 0
        purchase_price_groups[price] += qty_from_this_item

        # Add to total cost
        total_cost += price * qty_from_this_item

        # Reduce remaining quantity
        remaining_quantity -= qty_from_this_item

    if remaining_quantity > 0:
        product_additional_cost = product.productadditionalcost_set.first()
        price_to_use = product_additional_cost.amount if product_additional_cost else 0

        if price_to_use not in purchase_price_groups:
            purchase_price_groups[price_to_use] = 0
        purchase_price_groups[price_to_use] += remaining_quantity

        # Add to total cost
        total_cost += price_to_use * remaining_quantity

    return purchase_price_groups, total_cost
