from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


_PALETTE = ["#d946ef", "#6c5ce7", "#10b981", "#f59e0b", "#3b82f6", "#ef4444", "#06b6d4"]
_OTHER_COLOR = "#94a3b8"
_TOP_N = 5


class PrivateWeDashboardExpenseBreakdownView(DashboardCardView):
    """Card 24 — Expense Breakdown by account_type.

    Returns just the ``expenseBreakdown`` segments (top categories; the long
    tail is collapsed into "Other"). Error/restricted states are still emitted
    as envelopes by the base view.
    """

    card_key = "expense_breakdown"
    action_route = "/reports/expenses"

    def get_card_data(self, request, filters):
        rows, _total = finance.expense_breakdown(
            filters.company, filters.date_from, filters.date_to
        )

        named = rows[:_TOP_N]
        rest = rows[_TOP_N:]

        segments = []
        for index, row in enumerate(named):
            amount = row["amount"]
            segments.append(
                {
                    "name": row["category"],
                    "amount": amount,
                    "label": f"${amount:,.0f}",
                    "color": _PALETTE[index % len(_PALETTE)],
                }
            )

        if rest:
            other_amount = round(sum(r["amount"] for r in rest), 2)
            segments.append(
                {
                    "name": "Other",
                    "amount": other_amount,
                    "label": f"${other_amount:,.0f}",
                    "color": _OTHER_COLOR,
                }
            )

        return {"expenseBreakdown": segments}
