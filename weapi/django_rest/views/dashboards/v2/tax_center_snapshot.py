from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import tax


class PrivateWeDashboardTaxCenterSnapshotView(DashboardCardView):
    """Card 21 — Tax Center Snapshot (sales tax + payroll tax rollup).

    Returns just the ``taxes`` breakdown segments (shaped for a donut/bar
    chart). Error/restricted states are still emitted as envelopes by the base
    view.
    """

    card_key = "tax_center_snapshot"
    action_route = "/tax-center"

    def get_card_data(self, request, filters):
        snapshot = tax.tax_center_snapshot(
            filters.company,
            filters.date_from,
            filters.date_to,
            today=filters.today,
        )
        sales = snapshot["sales_tax"]
        payroll = snapshot["payroll_tax"]

        segments = [
            {"name": "Sales Tax", "amount": sales["liability"], "color": "#6c5ce7"},
            {"name": "Income Tax", "amount": payroll["employee_taxes"], "color": "#f59e0b"},
            {"name": "Payroll Tax", "amount": payroll["employer_taxes"], "color": "#10b981"},
        ]
        for segment in segments:
            segment["label"] = f"${segment['amount']:,.0f}"

        return {
            "totalTaxPayable": snapshot["total_liability"],
            "nextDueDate": sales["next_due_date"],
            "taxes": segments,
        }
