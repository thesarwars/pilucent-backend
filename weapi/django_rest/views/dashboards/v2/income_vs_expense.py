from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardIncomeVsExpenseView(DashboardCardView):
    """Card 04 — Income vs Expense.

    Returns just the ``incomeVsExpense`` monthly series. Error/restricted states
    are still emitted as envelopes by the base view.
    """

    card_key = "income_vs_expense"
    action_route = "/reports/profit-and-loss"
    ALLOWED_MONTH_WINDOWS = frozenset((3, 6, 7, 12))
    DEFAULT_MONTHS = 6

    def get_card_data(self, request, filters):
        months_param = request.query_params.get("months", str(self.DEFAULT_MONTHS))
        try:
            months = int(months_param)
        except (TypeError, ValueError):
            months = self.DEFAULT_MONTHS
        if months not in self.ALLOWED_MONTH_WINDOWS:
            months = self.DEFAULT_MONTHS

        rows = finance.income_expense_by_month(filters.company, months)
        income_vs_expense = [
            {
                "label": row["month"],
                "income": row["income"],
                "expenses": row["expense"],
            }
            for row in rows
        ]
        return {"incomeVsExpense": income_vs_expense}
