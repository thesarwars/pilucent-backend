from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


# bucket key -> (display name, chart color)
_BUCKET_META = {
    "current": ("Current", "#6c5ce7"),
    "1_30": ("1-30 Days", "#3b82f6"),
    "31_60": ("31-60 Days", "#10b981"),
    "61_90": ("61-90 Days", "#f59e0b"),
    "90_plus": ("90+ Days", "#ef4444"),
}


class PrivateWeDashboardArAgingView(DashboardCardView):
    """Card 22 — AR Aging (open receivables bucketed by due date).

    Returns just the ``arAging`` segments. Error/restricted states are still
    emitted as envelopes by the base view.
    """

    card_key = "ar_aging"
    action_route = "/sales/invoices"

    def get_card_data(self, request, filters):
        buckets = finance.ar_aging(filters.company, as_of=filters.today)

        segments = []
        for key in finance.AGING_BUCKETS:
            name, color = _BUCKET_META[key]
            amount = buckets[key]
            segments.append(
                {
                    "name": name,
                    "amount": amount,
                    "label": f"${amount:,.0f}",
                    "color": color,
                }
            )
        return {"arAging": segments}
