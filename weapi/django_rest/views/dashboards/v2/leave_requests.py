from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import hr


def _initials(name):
    if not name:
        return "?"
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _format_dates(from_date, to_date):
    if from_date is None:
        return None
    start = from_date.strftime("%b %d")
    if to_date is None or to_date == from_date:
        return start
    return f"{start} - {to_date.strftime('%b %d')}"


class PrivateWeDashboardLeaveRequestsView(DashboardCardView):
    """Card 08 — Leave Requests.

    Returns just the pending ``leaveRequests`` list. Error/restricted states are
    still emitted as envelopes by the base view.
    """

    card_key = "leave_requests"
    action_route = "/hr/leave-requests"

    def get_card_data(self, request, filters):
        pending = hr.pending_leave_requests(filters.company, limit=5)

        leave_requests = []
        for lr in pending:
            employee = lr.employee
            name = getattr(employee, "name_en", None) or "Unknown"
            days = lr.total_days or 0
            leave_requests.append(
                {
                    "name": name,
                    "avatar": _initials(name),
                    "type": lr.leave_type.title if lr.leave_type_id else None,
                    "dates": _format_dates(lr.from_date, lr.to_date),
                    "days": f"{days} day" + ("s" if days != 1 else ""),
                }
            )

        return {"leaveRequests": leave_requests}
