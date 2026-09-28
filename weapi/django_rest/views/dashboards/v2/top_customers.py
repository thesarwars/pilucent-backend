from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardTopCustomersView(DashboardCardView):
    """Card 16 — Top Customers by revenue for the period.

    Returns just the ``topCustomers`` list. Error/restricted states are still
    emitted as envelopes by the base view.
    """

    card_key = "top_customers"
    action_route = "/sales/customers"

    def get_card_data(self, request, filters):
        try:
            limit = int(request.query_params.get("limit", "5"))
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 20))

        rows, _total = finance.top_customers(
            filters.company, filters.date_from, filters.date_to, limit=limit
        )

        top_customers = [
            {
                "name": row["name"],
                "value": f"${row['revenue']:,.0f}",
                "percent": round(row["percent"]),
            }
            for row in rows
        ]
        return {"topCustomers": top_customers}
