"""Inventory aggregations for v2 dashboard cards.

Inventory value uses a simple unit-cost approach (quantity x latest
ProductAdditionalCost.amount), matching the stock-adjustment valuation used
elsewhere. FIFO-accurate valuation is intentionally out of scope here.
"""

from decimal import Decimal

from django.db.models import (
    DecimalField,
    F,
    OuterRef,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce

from productio.models import Product, ProductAdditionalCost
from productio.choices import ProductStatusChoices


ZERO = Decimal("0.00")


def _inventory_products(company):
    unit_cost_sq = (
        ProductAdditionalCost.objects.filter(product=OuterRef("pk"))
        .order_by("created_at")
        .values("amount")[:1]
    )
    return (
        Product.objects.filter(Product.stocked_filter_for(), company=company)
        .exclude(status=ProductStatusChoices.REMOVED)
        .annotate(
            unit_cost=Coalesce(
                Subquery(unit_cost_sq, output_field=DecimalField()),
                ZERO,
                output_field=DecimalField(),
            )
        )
    )


def inventory_value(company):
    qs = _inventory_products(company).annotate(
        line_value=F("quantity") * F("unit_cost")
    )
    return qs.aggregate(
        total=Coalesce(Sum("line_value"), ZERO, output_field=DecimalField())
    )["total"]


def low_stock_items(company, limit=None):
    """Products at or below their reorder point (out-of-stock first)."""
    qs = (
        Product.objects.filter(Product.stocked_filter_for(), company=company)
        .exclude(status=ProductStatusChoices.REMOVED)
        .filter(reorder_point__isnull=False, quantity__lte=F("reorder_point"))
        .order_by("quantity")
    )
    if limit:
        qs = qs[:limit]
    return qs
