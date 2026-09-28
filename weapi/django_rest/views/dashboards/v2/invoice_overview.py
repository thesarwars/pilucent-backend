from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardInvoiceOverviewView(DashboardCardView):
    """Card 11 — Invoice Overview.

    Outstanding receivables use ``due_total`` (open balance), and overdue is
    computed (``due_date < today AND due_total > 0``) because there is no
    OVERDUE status in the sales enum. Returns just the ``invoices`` segments
    list (shaped for a donut/bar chart); error/restricted states are still
    emitted as envelopes by the base view.
    """

    card_key = "invoice_overview"
    action_route = "/sales/invoices"

    @staticmethod
    def _money(value):
        return f"${value:,.0f}"

    def get_card_data(self, request, filters):
        dist = finance.invoice_status_distribution(
            filters.company, filters.date_from, filters.date_to
        )

        segments = [
            {"name": "Paid", "amount": dist["paid"]["amount"], "color": "#10b981"},
            {"name": "Pending", "amount": dist["pending"]["amount"], "color": "#f59e0b"},
            {"name": "Overdue", "amount": dist["overdue"]["amount"], "color": "#ef4444"},
        ]
        for segment in segments:
            segment["label"] = self._money(segment["amount"])

        return {"invoices": segments}
