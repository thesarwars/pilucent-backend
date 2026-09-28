from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard.envelope import compute_trend
from weapi.django_rest.helpers.dashboard import finance


_DIRECTION_MAP = {"up": "up", "down": "down", "flat": "neutral", "new": "neutral"}


def _trend(current, previous):
    percent, direction = compute_trend(current, previous)
    fe_direction = _DIRECTION_MAP.get(direction, "neutral")
    text = "New" if percent is None else f"{percent:+.1f}%"
    return text, fe_direction


def _money(value):
    return f"${float(value or 0):,.0f}"


class PrivateWeDashboardMiniExpenseCashView(DashboardCardView):
    """Card 19 — Mini Expense & Cash (compact combined tile).

    Returns ``totalExpense`` + ``availableCash`` stat tiles and a computed
    ``cashHealthScore``. Error/restricted states are still emitted as envelopes
    by the base view.
    """

    card_key = "mini_expense_cash"
    action_route = "/reports/expenses"

    def get_card_data(self, request, filters):
        company = filters.company

        _, expense = finance.coa_income_expense(
            company, filters.date_from, filters.date_to
        )
        _, prev_expense = finance.coa_income_expense(
            company, filters.previous_date_from, filters.previous_date_to
        )

        cash = float(finance.cash_balance(company))
        inflow, outflow = finance.cash_in_out(
            company, filters.date_from, filters.date_to
        )
        # Approximate prior cash from the period's net movement.
        prev_cash = cash - (float(inflow) - float(outflow))

        expense_trend, expense_dir = _trend(expense, prev_expense)
        cash_trend, cash_dir = _trend(cash, prev_cash)

        return {
            "totalExpense": {
                "label": "Total Expense",
                "value": _money(expense),
                "trend": expense_trend,
                "trendDirection": expense_dir,
                "helper": "vs last month",
            },
            "availableCash": {
                "label": "Available Cash",
                "value": _money(cash),
                "trend": cash_trend,
                "trendDirection": cash_dir,
                "helper": "vs last month",
            },
            "cashHealthScore": {
                "score": finance.cash_health_score(company),
                "label": "Cash health score",
            },
        }
