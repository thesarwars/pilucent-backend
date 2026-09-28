from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import hr


class PrivateWeDashboardTodaysWorkforceView(DashboardCardView):
    """Card 09 — Today's Workforce (approximation).

    There is no per-day roster model, so "scheduled" approximates active
    employees with an assigned shift. Returns just the ``workforce`` segments
    list (shaped for a donut/pie chart). Error/restricted states are still
    emitted as envelopes by the base view.
    """

    card_key = "todays_workforce"
    action_route = "/hr/attendance"

    def get_card_data(self, request, filters):
        workforce = hr.todays_workforce(filters.company, day=filters.today)
        segments = [
            {"name": "On Shift", "value": workforce["on_shift"], "color": "#6c5ce7"},
            {"name": "Yet to Check-in", "value": workforce["yet_to_check_in"], "color": "#f59e0b"},
            {"name": "On Leave", "value": workforce["on_leave"], "color": "#22c55e"},
            {"name": "Absent", "value": workforce["absent"], "color": "#ef4444"},
        ]
        return {"workforce": segments}
