from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import insights


class PrivateWeDashboardAiInsightsView(DashboardCardView):
    """Card 05 — AI Business Insights (deterministic rules engine).

    Returns just the ``insights`` list. Error/restricted states are still
    emitted as envelopes by the base view.
    """

    card_key = "ai_insights"
    action_route = "/dashboard"

    def get_card_data(self, request, filters):
        return {"insights": insights.generate_insights(filters.company, filters)}
