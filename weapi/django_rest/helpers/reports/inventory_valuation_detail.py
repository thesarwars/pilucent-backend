"""Inventory Valuation Detail report builder.

A transaction-by-transaction ledger per inventory item, read straight from the
``stockio.StockMovement`` ledger (see
``docs/updated-prompts/Inventory_Valuation_Detail_Report_Documentation.md``). For
each product it lists every movement in date order with the signed quantity, the
per-line rate, the signed inventory cost (FIFO COGS on outbound), and the running
quantity-on-hand and asset value after each one, plus a per-item subtotal and a
grand total.

Coverage note: the ledger is authoritative from the OPENING seed forward.
Products/periods with no ledger rows show nothing here — the running balances are
only meaningful once a product has an OPENING movement (rollout seed) and its
movements are captured. This is why the report reads the ledger rather than
replaying the (lossy) source documents.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from stockio.choices import StockMovementTypeChoices
from productio.models import Product
from stockio.models import StockMovement

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# Human labels for the Transaction type column.
_TYPE_LABELS = dict(StockMovementTypeChoices.choices)


def _money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def assemble_detail(movements, as_of):
    """Pure: group ordered ``movements`` into per-product blocks with subtotals.

    ``movements`` is an iterable of dicts **ordered by (product, date, created_at)**
    with: ``product_uid``, ``product``, ``sku``, ``uid``, ``date`` (iso str),
    ``type``, ``quantity`` (signed number), ``rate``, ``inventory_cost``.

    Running quantity-on-hand and asset value are **derived here** by cumulating
    the signed quantity / inventory cost in date order within each product — NOT
    read from the stored rows — so a backdated movement sorts into place and the
    running column, subtotal, and grand total are always correct. Kept ORM-free
    for unit testing.
    """
    groups = []
    current = None
    total_value = ZERO

    def _close(group):
        # subtotal = the final cumulative balances of the group.
        group["subtotal"] = {
            "quantity": float(group["_run_qty"]),
            "inventory_cost": float(_money(group["_cost_sum"])),
            "asset_value": float(_money(group["_run_val"])),
        }
        return _money(group["_run_val"])

    for mv in movements:
        key = mv["product_uid"]
        if current is None or current["uid"] != key:
            if current is not None:
                total_value += _close(current)
            current = {
                "uid": key,
                "product": mv.get("product"),
                "sku": mv.get("sku") or "",
                "rows": [],
                "_cost_sum": ZERO,
                "_run_qty": Decimal("0"),
                "_run_val": ZERO,
            }
            groups.append(current)

        cost = _money(mv["inventory_cost"])
        current["_cost_sum"] += cost
        current["_run_qty"] += Decimal(str(mv["quantity"]))
        current["_run_val"] += cost
        current["rows"].append(
            {
                "uid": mv.get("uid"),
                "date": mv["date"],
                "transaction_type": _TYPE_LABELS.get(mv["type"], mv["type"]),
                "type": mv["type"],
                "quantity": float(mv["quantity"]),
                "rate": float(_money(mv["rate"])) if mv.get("rate") is not None else None,
                "inventory_cost": float(cost),
                "running_quantity": float(current["_run_qty"]),
                "running_value": float(_money(current["_run_val"])),
            }
        )

    if current is not None:
        total_value += _close(current)

    for group in groups:
        for key in ("_cost_sum", "_run_qty", "_run_val"):
            group.pop(key, None)

    return {
        "as_of": as_of.isoformat(),
        "groups": groups,
        "total": {"asset_value": float(_money(total_value))},
    }


def inventory_valuation_detail(company, as_of=None):
    """Build the full Inventory Valuation Detail for ``company`` up to ``as_of``."""
    as_of = as_of or date.today()
    qs = (
        StockMovement.objects.filter(
            # The same predicate the posting paths use, so the ledger and this
            # report can tie. It filtered on `is_inventory` while posting
            # decided by item type, which is how twenty services came to be
            # counted as inventory on production.
            Product.stocked_filter_for("product"),
            company=company,
            date__lte=as_of,
        )
        .select_related("product")
        .order_by("product__title", "product__sku", "product_id", "date", "created_at", "id")
    )
    movements = [
        {
            "uid": str(mv.uid),
            "product_uid": str(mv.product.uid),
            "product": mv.product.title,
            "sku": mv.product.sku,
            "date": mv.date.isoformat(),
            "type": mv.movement_type,
            "quantity": mv.signed_quantity,
            "rate": mv.rate,
            "inventory_cost": mv.inventory_cost,
        }
        for mv in qs
    ]
    return assemble_detail(movements, as_of)
