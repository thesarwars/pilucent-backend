from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import hr


class PrivateWeDashboardAttendanceSummaryView(DashboardCardView):
    """Card 06 — Attendance Summary (applies CompanyShift.grace_time).

    Returns just the ``attendance`` stat-card list. Error/restricted states are
    still emitted as envelopes by the base view.
    """

    card_key = "attendance_summary"
    action_route = "/hr/attendance"

    @staticmethod
    def _pct(part, whole):
        return round((part / whole * 100), 1) if whole else 0.0

    def get_card_data(self, request, filters):
        summary = hr.attendance_summary(filters.company, day=filters.today)
        scheduled = summary["scheduled"]
        rate = summary["attendance_rate"]
        avg_7 = hr.attendance_rate_average(filters.company, day=filters.today, days=7)
        delta = round(rate - avg_7, 1)

        attendance = [
            {
                "label": "Present today",
                "value": str(summary["present"]),
                "helper": f"{self._pct(summary['present'], scheduled)}%",
                "tone": "green",
            },
            {
                "label": "Late check-ins",
                "value": str(summary["late"]),
                "helper": f"{self._pct(summary['late'], scheduled)}%",
                "tone": "orange",
            },
            {
                "label": "On leave",
                "value": str(summary["on_leave"]),
                "helper": f"{self._pct(summary['on_leave'], scheduled)}%",
                "tone": "rose",
            },
            {
                "label": "Attendance rate",
                "value": f"{rate}%",
                "helper": f"{delta:+.1f}% vs last 7 days",
                "tone": "green",
            },
        ]
        return {"attendance": attendance}
