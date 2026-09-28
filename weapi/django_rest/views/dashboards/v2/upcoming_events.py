from datetime import date

from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import hr


# Maps a derived event type to its display title/subtitle/icon. ``title`` is a
# callable so person-events can use the employee name where appropriate.
_EVENT_DISPLAY = {
    "birthday": {"subtitle": "Birthday", "icon": "calendar", "name_as_title": True},
    "work_anniversary": {"subtitle": None, "icon": "party", "title": "Work Anniversary"},
    "contract_end": {"subtitle": None, "icon": "file", "title": "Contract Ending"},
}


class PrivateWeDashboardUpcomingEventsView(DashboardCardView):
    """Card 10 — Upcoming Events (approximation).

    Derived from employee birthdays, work anniversaries, and contract-end
    dates. There is no manual HR calendar model, so only person-derived events
    are returned. Returns just the ``upcomingEvents`` list; error/restricted
    states are still emitted as envelopes by the base view.
    """

    card_key = "upcoming_events"
    action_route = "/hr/employees"
    DEFAULT_WINDOW_DAYS = 30

    @staticmethod
    def _format_date(iso_value):
        if not iso_value:
            return None
        try:
            return date.fromisoformat(iso_value).strftime("%b %d")
        except (TypeError, ValueError):
            return iso_value

    def get_card_data(self, request, filters):
        try:
            days = int(request.query_params.get("days", str(self.DEFAULT_WINDOW_DAYS)))
        except (TypeError, ValueError):
            days = self.DEFAULT_WINDOW_DAYS
        days = max(1, min(days, 365))

        events = hr.upcoming_events(filters.company, days=days)

        upcoming_events = []
        for event in events:
            display = _EVENT_DISPLAY.get(event["type"], {})
            name = event.get("name") or "Employee"
            if display.get("name_as_title"):
                title, subtitle = name, display.get("subtitle")
            else:
                title, subtitle = display.get("title", event["type"]), name
            upcoming_events.append(
                {
                    "title": title,
                    "subtitle": subtitle,
                    "date": self._format_date(event.get("date")),
                    "icon": display.get("icon", "calendar"),
                }
            )

        return {"upcomingEvents": upcoming_events}
