from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardCashFlowView(DashboardCardView):
    """Card 02 — Cash Flow Overview (inflow/outflow from the bank feed).

    Returns just the ``cashFlow`` series (date-bucketed over the selected
    range). Error/restricted states are still emitted as envelopes by the base
    view.
    """

    card_key = "cash_flow"
    action_route = "/banking/transactions"
    DEFAULT_BUCKETS = 7

    def get_card_data(self, request, filters):
        try:
            buckets = int(request.query_params.get("buckets", str(self.DEFAULT_BUCKETS)))
        except (TypeError, ValueError):
            buckets = self.DEFAULT_BUCKETS
        buckets = max(1, min(buckets, 60))

        series = finance.cash_flow_series(
            filters.company, filters.date_from, filters.date_to, buckets=buckets
        )
        return {"cashFlow": series}
