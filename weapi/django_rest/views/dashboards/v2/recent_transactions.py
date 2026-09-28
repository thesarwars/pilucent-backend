from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import transactions


class PrivateWeDashboardRecentTransactionsView(DashboardCardView):
    """Card 12 — Recent Transactions.

    One row per posted ``JournalEntry`` (a transaction document), newest first.
    Returns just the ``recentTransactions`` list; error/restricted states are
    still emitted as envelopes by the base view.
    """

    card_key = "recent_transactions"
    action_route = "/banking/transactions"
    DEFAULT_LIMIT = 10

    def get_card_data(self, request, filters):
        try:
            limit = int(request.query_params.get("limit", str(self.DEFAULT_LIMIT)))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = max(1, min(limit, 50))

        return {
            "recentTransactions": transactions.recent_transactions(
                filters.company, limit=limit
            )
        }
