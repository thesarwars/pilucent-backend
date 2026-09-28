from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardTopSellingProductsView(DashboardCardView):
    """Card 17 — Top Selling Products (net of refunds) for the period.

    Returns just the ``topProducts`` list (``value`` = units sold, ``secondary``
    = revenue). Error/restricted states are still emitted as envelopes by the
    base view.
    """

    card_key = "top_selling_products"
    action_route = "/inventory/products"

    def get_card_data(self, request, filters):
        try:
            limit = int(request.query_params.get("limit", "5"))
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 20))

        rows, _total = finance.top_selling_products(
            filters.company, filters.date_from, filters.date_to, limit=limit
        )

        top_products = [
            {
                "name": row["name"],
                "value": f"{row['quantity']:,}",
                "secondary": f"${row['revenue']:,.0f}",
                "percent": round(row["percent"]),
            }
            for row in rows
        ]
        return {"topProducts": top_products}
