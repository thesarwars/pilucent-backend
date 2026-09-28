from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardProfitLossView(DashboardCardView):
    """Card 03 — Profit & Loss Graph.

    Returns just the ``profitLoss`` monthly series. Error/restricted states are
    still emitted as envelopes by the base view.
    """

    card_key = "profit_loss"
    action_route = "/reports/profit-and-loss"
    ALLOWED_MONTH_WINDOWS = frozenset((3, 6, 7, 12))
    DEFAULT_MONTHS = 12

    def get_card_data(self, request, filters):
        months_param = request.query_params.get("months", str(self.DEFAULT_MONTHS))
        try:
            months = int(months_param)
        except (TypeError, ValueError):
            months = self.DEFAULT_MONTHS
        if months not in self.ALLOWED_MONTH_WINDOWS:
            months = self.DEFAULT_MONTHS

        rows = finance.income_expense_by_month(filters.company, months)
        profit_loss = [
            {
                "label": row["month"],
                "revenue": row["income"],
                "expenses": row["expense"],
                "profit": round(row["income"] - row["expense"], 2),
            }
            for row in rows
        ]
        return {"profitLoss": profit_loss}
