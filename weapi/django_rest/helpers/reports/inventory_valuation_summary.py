"""Inventory Valuation Summary report builder.

Builds the Inventory Valuation Summary described in
``docs/updated-prompts/Inventory_Valuation_Summary_Documentation.md``: one row per
inventory item with its on-hand quantity, the cost value of those units (Asset
Value), and the average unit cost (Calc. Avg = Asset Value / Qty), plus a totals
row whose Calc. Avg is the *weighted* blend (Total Asset Value / Total Qty).

Valuation reuses the canonical dashboard computation
(``weapi/django_rest/helpers/dashboard/inventory.py``): inventory items are
``Product(is_inventory=True)`` (excluding REMOVED), on-hand quantity is the stored
``Product.quantity``, and unit cost is the product's ``ProductAdditionalCost``
amount; Asset Value = quantity x unit_cost -- the same valuation as the v2
dashboard inventory-value card. Per-row Asset Values are rounded to the cent and
the total is their sum (so the displayed column adds up); this can differ from
the dashboard card's single-rounded raw total by a few cents when unit costs
carry a third decimal. FIFO-accurate layer valuation is intentionally out of
scope, matching that card; the per-product unit cost is whatever
``_inventory_products`` selects (a single ProductAdditionalCost amount).

Snapshot note: quantity/value are read as they stand *now* (the "All Dates / as
of today" view). Historical as-of valuation -- replaying movements to a past date
-- is not yet supported.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import DecimalField, F
from django.db.models.functions import Coalesce

from weapi.django_rest.helpers.dashboard.inventory import ZERO, _inventory_products

CENT = Decimal("0.01")


def _money(value):
    """Quantize to 2 dp so listed rows add up to the displayed total."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def assemble_valuation(items, as_of):
    """Pure: shape ``items`` into per-item rows + a weighted totals row.

    ``items`` is an iterable of dicts with ``uid``, ``product`` (name), ``sku``,
    ``quantity`` (number) and ``asset_value`` (Decimal cost of on-hand units).
    Calc. Avg per item = Asset Value / Qty; the total Calc. Avg is the weighted
    blend Total Asset Value / Total Qty (NOT the average of per-item averages).
    Kept ORM-free so the two-pass math is unit-testable against the worked example.
    """
    rows = []
    total_qty = Decimal("0")
    total_value = ZERO
    for item in items:
        qty = Decimal(str(item["quantity"] or 0))
        value = _money(item["asset_value"] or ZERO)
        calc_avg = _money(value / qty) if qty else ZERO
        total_qty += qty
        total_value += value
        rows.append(
            {
                "uid": item.get("uid"),
                "product": item.get("product"),
                "sku": item.get("sku") or "",
                "quantity": float(qty),
                "asset_value": float(value),
                "calc_avg": float(calc_avg),
            }
        )

    total_calc_avg = _money(total_value / total_qty) if total_qty else ZERO
    return {
        "as_of": as_of.isoformat(),
        "rows": rows,
        "total": {
            "quantity": float(total_qty),
            "asset_value": float(total_value),
            "calc_avg": float(total_calc_avg),
        },
    }


def inventory_valuation_summary(company, as_of=None):
    """Build the full Inventory Valuation Summary for ``company`` (current snapshot)."""
    as_of = as_of or date.today()
    qs = (
        _inventory_products(company)
        .annotate(
            line_value=Coalesce(
                F("quantity") * F("unit_cost"), ZERO, output_field=DecimalField()
            )
        )
        .order_by("title", "sku")  # default: by item name
    )
    items = [
        {
            "uid": str(product.uid),
            "product": product.title,
            "sku": product.sku,
            "quantity": product.quantity or 0,
            "asset_value": product.line_value or ZERO,
        }
        for product in qs
    ]
    return assemble_valuation(items, as_of)
