from django.db.models import Prefetch
from django.utils import timezone

from .base import DashboardCardView

from messageio.models import Inbox, Thread
from messageio.choices import InboxStatusChoices, InboxKindChoices, ThreadKindChoices


_OPEN_STATUSES = [
    InboxStatusChoices.OPEN,
    InboxStatusChoices.PENDING,
    InboxStatusChoices.ON_GOING,
]


class PrivateWeDashboardSupportTicketsView(DashboardCardView):
    """Card 14 — Open Support Tickets (approximation).

    Priority/SLA are not modeled, so ``priority`` is DERIVED from ticket age
    (older open tickets rank higher). The ticket subject is the parent thread's
    content. Returns just the ``supportTickets`` list; error/restricted states
    are still emitted as envelopes by the base view.
    """

    card_key = "support_tickets"
    action_route = "/support/tickets"
    required_feature = "is_support_ticket"
    DEFAULT_LIMIT = 10

    @staticmethod
    def _priority(age_days):
        if age_days is None:
            return "Low"
        if age_days >= 2:
            return "High"
        if age_days >= 1:
            return "Medium"
        return "Low"

    @staticmethod
    def _age(created, now):
        if created is None:
            return None
        seconds = (now - created).total_seconds()
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        if seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"

    @staticmethod
    def _subject(ticket):
        parent = next(iter(ticket.thread_set.all()), None)
        text = getattr(ticket, "title", None) or (parent.content if parent else None)
        if not text:
            return "Support ticket"
        text = text.strip()
        return text if len(text) <= 80 else text[:77] + "..."

    def get_card_data(self, request, filters):
        try:
            limit = int(request.query_params.get("limit", str(self.DEFAULT_LIMIT)))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = max(1, min(limit, 50))

        now = timezone.now()
        user_ids = filters.company.companyuser_set.values_list("user_id", flat=True)
        qs = (
            Inbox.objects.filter(
                kind=InboxKindChoices.SUPPORT_AND_TICKET,
                status__in=_OPEN_STATUSES,
                user_id__in=user_ids,
            )
            .prefetch_related(
                Prefetch(
                    "thread_set",
                    queryset=Thread.objects.filter(
                        kind=ThreadKindChoices.PARENT
                    ).order_by("created_at"),
                )
            )
            .order_by("-created_at")
        )

        support_tickets = []
        for ticket in qs[:limit]:
            created = ticket.created_at
            age_days = (now - created).days if created else None
            support_tickets.append(
                {
                    "title": self._subject(ticket),
                    "code": f"#{ticket.ticket_noumber}" if ticket.ticket_noumber else None,
                    "priority": self._priority(age_days),
                    "age": self._age(created, now),
                }
            )

        return {"supportTickets": support_tickets}
