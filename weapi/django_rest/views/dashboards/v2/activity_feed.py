from auditlog.models import LogEntry

from .base import DashboardCardView


# audit action (int) -> past-tense verb + UI tone
_ACTION_WORD = {0: "created", 1: "updated", 2: "deleted", 3: "viewed"}
_ACTION_TYPE = {0: "success", 1: "info", 2: "danger", 3: "info"}


class PrivateWeDashboardActivityFeedView(DashboardCardView):
    """Card 15 — Activity Feed (recent audit log entries).

    Sourced from ``auditlog.LogEntry`` (CRUD events). The audit log does not
    store monetary amounts, so ``amount`` is not emitted; ``type`` is derived
    from the audit action. Returns just the ``activityFeed`` list; error/
    restricted states are still emitted as envelopes by the base view.
    """

    card_key = "activity_feed"
    action_route = "/audit-logs"
    required_feature = "is_audit_log"
    DEFAULT_LIMIT = 10

    @staticmethod
    def _title(entry):
        content_name = None
        if entry.content_type:
            content_name = entry.content_type.model_class()._meta.verbose_name.title()
        verb = _ACTION_WORD.get(entry.action, "changed")
        obj = (entry.object_repr or "").strip()
        if len(obj) > 60:
            obj = obj[:57] + "..."
        parts = [p for p in (content_name, obj, verb) if p]
        return " ".join(parts) or "Activity"

    def get_card_data(self, request, filters):
        try:
            limit = int(request.query_params.get("limit", str(self.DEFAULT_LIMIT)))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = max(1, min(limit, 50))

        user_ids = filters.company.companyuser_set.values_list("user_id", flat=True)
        entries = (
            LogEntry.objects.filter(actor_id__in=user_ids)
            .select_related("actor", "content_type")
            .order_by("-timestamp")[:limit]
        )

        activity_feed = []
        for entry in entries:
            activity_feed.append(
                {
                    "title": self._title(entry),
                    "meta": entry.timestamp.strftime("%b %d, %I:%M %p")
                    if entry.timestamp
                    else None,
                    "type": _ACTION_TYPE.get(entry.action, "info"),
                }
            )

        return {"activityFeed": activity_feed}
