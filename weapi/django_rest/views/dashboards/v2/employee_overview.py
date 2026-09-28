from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import hr


class PrivateWeDashboardEmployeeOverviewView(DashboardCardView):
    """Card 07 — Employee Overview.

    Returns just the ``employees`` stat-card list. Error/restricted states are
    still emitted as envelopes by the base view.

    NOTE: "Open positions" has no backing recruitment model yet, so it is a
    placeholder (0). Add a recruitment/job-opening model to populate it.
    """

    card_key = "employee_overview"
    action_route = "/hr/employees"

    def get_card_data(self, request, filters):
        stats = hr.employee_stats(filters.company, today=filters.today)

        employees = [
            {
                "label": "Total employees",
                "value": str(stats["total_active"]),
                "helper": f"{stats['net_change']:+d} vs last month",
                "tone": "purple",
            },
            {
                "label": "New joiners",
                "value": str(stats["joiners_this_month"]),
                "helper": f"{stats['joiners_this_month']:+d} this month",
                "tone": "blue",
            },
            {
                "label": "Open positions",
                "value": "0",
                "helper": "not tracked yet",
                "tone": "orange",
            },
            {
                "label": "Upcoming confirmations",
                "value": str(stats["upcoming_confirmations"]),
                "helper": "in next 30 days",
                "tone": "purple",
            },
        ]
        return {"employees": employees}
