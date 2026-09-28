import logging

from django.db.models import Q

from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
from purchaseio.models import PurchaseItem


def get_latest_published_purchase_item(product, company, date):
    """
    Get the latest published purchase item for a given product, company and date.

    Args:
        product: The product instance to get purchase item for
        company: The company instance
        date: The date to compare against purchase date

    Returns:
        PurchaseItem: Returns the first matching purchase item or None if not found
    """
    valid_statuses = [
        PurchaseStatus.OPEN,
        PurchaseStatus.ACCEPTED,
        PurchaseStatus.CLOSED,
        PurchaseStatus.COMPLETED,
    ]

    return (
        PurchaseItem.objects.filter(
            product=product,
            status=PurchaseItemStatus.PUBLISHED,
            purchase__company=company,
            purchase__status__in=valid_statuses,
            purchase__date__lte=date,
        )
        .order_by("created_at")
        .filter(
            Q(purchase__is_bill=True)
            | Q(purchase__is_cheque=True)
            | Q(purchase__is_via_expense=True)
        )
        .first()
    )


logger = logging.getLogger(__name__)


def record_purchase_line_movement(
    purchase, item, product, quantity, *, unit_cost=None, inbound=True, note=None
):
    """Append the stock-ledger movement for one purchase line.

    The bill-create path has recorded its `PURCHASE` movement since the ledger
    was built. The four paths that CHANGE a posted bill did not -- adding a line
    to an existing bill, editing a line's opening quantity, the expense route,
    and deleting a line. So stock arrived and left with no ledger trace, which is
    the standing posting-leg mirror rule in the shape it takes here: the create
    leg was wired and its amend and delete twins were not.

    Inbound is a `PURCHASE`: the line IS the cost layer, so it carries a rate and
    no slices. Outbound is a `REVERSAL` -- not a `PURCHASE_RETURN`, because
    nothing is going back to the supplier; the document is being unwound. It
    consumes the layer this line created first (`prefer_movement`), so undoing a
    bill takes the units off their own lot rather than repricing whatever stock
    happens to be oldest.

    Best-effort: a ledger failure must not take the posting down with it.
    """
    quantity = int(quantity or 0)
    if product is None or not quantity:
        return None

    try:
        from stockio.choices import StockMovementTypeChoices
        from stockio.django_rest.services.stock_movement import (
            consumption_slices,
            record_stock_movement,
        )
        from stockio.models import StockMovement

        common = dict(
            company=purchase.company,
            product=product,
            date=getattr(purchase, "date", None) or getattr(purchase, "bill_date", None),
            rate=unit_cost,
            created_by=getattr(purchase, "created_by", None),
            purchase_item=item,
            note=note,
        )

        if inbound:
            return record_stock_movement(
                movement_type=StockMovementTypeChoices.PURCHASE,
                signed_quantity=quantity,
                **common,
            )

        own_layer = (
            StockMovement.objects.filter(
                purchase_item=item, signed_quantity__gt=0
            )
            .order_by("date", "id")
            .first()
            if item is not None
            else None
        )
        # No fallback slice, and the movement is capped at what the layers
        # actually still hold. Deleting a bill line whose goods have already
        # been SOLD is a contradiction, and the conservative reading is the only
        # honest one: you cannot un-buy what has left the building. Reversing the
        # full line instead drove on-hand to -7 on a bill of 10 with 7 sold,
        # while the layers read 0 -- the two halves of this ledger disagreeing,
        # which is the whole condition these steps exist to remove.
        #
        # A purchase RETURN is different and keeps its fallback: there the goods
        # physically go back to the supplier whether or not a layer explains
        # them. Here nothing moves; a document is being corrected.
        slices, unplaced = consumption_slices(
            product, quantity, prefer_movement=own_layer
        )
        return record_stock_movement(
            movement_type=StockMovementTypeChoices.REVERSAL,
            signed_quantity=-(quantity - unplaced),
            layer_slices=slices,
            **common,
        )
    except Exception:
        logger.exception(
            "stock ledger: failed to record purchase line %s for product %s",
            getattr(item, "pk", None), getattr(product, "pk", None),
        )
        return None
