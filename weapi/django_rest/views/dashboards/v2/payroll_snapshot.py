from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import hr


class PrivateWeDashboardPayrollSnapshotView(DashboardCardView):
    """Card 20 — Payroll Snapshot (FINALIZED runs only).

    Returns just the ``payroll`` breakdown segments (shaped for a donut/bar
    chart). Error/restricted states are still emitted as envelopes by the base
    view.
    """

    card_key = "payroll_snapshot"
    action_route = "/payroll/runs"
    required_feature = "is_payroll"

    def get_card_data(self, request, filters):
        breakdown = hr.payroll_breakdown(
            filters.company, filters.date_from, filters.date_to
        )

        segments = [
            {"name": "Gross Salary", "value": breakdown["gross_salary"], "color": "#6c5ce7"},
            {"name": "Allowances", "value": breakdown["allowances"], "color": "#10b981"},
            {"name": "Deductions", "value": breakdown["deductions"], "color": "#f59e0b"},
            {"name": "Taxes", "value": breakdown["taxes"], "color": "#3b82f6"},
            {"name": "Net Pay", "value": breakdown["net"], "color": "#ef4444"},
        ]
        for segment in segments:
            segment["amount"] = f"${segment['value']:,.0f}"

        return {"payroll": segments}
