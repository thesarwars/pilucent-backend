from typing import Any

from subscriptionio.choices import SubscriptionEventSourceChoices, SubscriptionEventTypeChoices
from subscriptionio.models import SubscriptionEvent


class SubscriptionEventService:
    @classmethod
    def record(
        cls,
        *,
        company,
        event_type: str,
        company_subscription=None,
        previous_status: str | None = None,
        new_status: str | None = None,
        source: str = SubscriptionEventSourceChoices.SYSTEM,
        payload: dict[str, Any] | None = None,
        actor=None,
        stripe_event_id: str | None = None,
    ) -> SubscriptionEvent:
        return SubscriptionEvent.objects.create(
            company=company,
            company_subscription=company_subscription,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            source=source,
            payload=payload or {},
            actor=actor,
            stripe_event_id=stripe_event_id,
            title=SubscriptionEventTypeChoices(event_type).label,
        )

    @classmethod
    def get_company_timeline(cls, company, *, limit: int = 50) -> list[dict[str, Any]]:
        events = (
            SubscriptionEvent.objects.filter(company=company)
            .select_related("company_subscription", "actor")
            .order_by("-created_at")[:limit]
        )
        return [
            {
                "uid": str(event.uid),
                "event_type": event.event_type,
                "previous_status": event.previous_status,
                "new_status": event.new_status,
                "source": event.source,
                "payload": event.payload,
                "created_at": event.created_at,
                "actor_uid": str(event.actor.uid) if event.actor else None,
            }
            for event in events
        ]
