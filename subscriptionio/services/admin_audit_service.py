from typing import Any

from django.db.models import Q

from subscriptionio.choices import SubscriptionEventTypeChoices
from subscriptionio.models import SubscriptionEvent


class AdminAuditService:
    CATEGORY_EVENT_TYPES: dict[str, list[str]] = {
        "plan": [SubscriptionEventTypeChoices.PLAN_CHANGED],
        "billing": [
            SubscriptionEventTypeChoices.CHECKOUT_COMPLETED,
            SubscriptionEventTypeChoices.PAYMENT_FAILED,
            SubscriptionEventTypeChoices.PAYMENT_RECOVERED,
            SubscriptionEventTypeChoices.DUNNING_GRACE,
            SubscriptionEventTypeChoices.DUNNING_SUSPENDED,
            SubscriptionEventTypeChoices.DUNNING_EXPIRED,
            SubscriptionEventTypeChoices.SUBSCRIPTION_CANCELED,
            SubscriptionEventTypeChoices.SUBSCRIPTION_REACTIVATED,
        ],
        "trial": [
            SubscriptionEventTypeChoices.TRIAL_STARTED,
            SubscriptionEventTypeChoices.TRIAL_EXPIRED,
            SubscriptionEventTypeChoices.TRIAL_CONVERTED,
        ],
        "coupon": [SubscriptionEventTypeChoices.CHECKOUT_COMPLETED],
        "referral": [
            SubscriptionEventTypeChoices.REFERRAL_APPROVED,
            SubscriptionEventTypeChoices.REFERRAL_REJECTED,
            SubscriptionEventTypeChoices.REFERRAL_REDEEMED,
        ],
    }

    @classmethod
    def _serialize_event(cls, event: SubscriptionEvent) -> dict[str, Any]:
        actor_name = None
        if event.actor:
            actor_name = getattr(event.actor, "name", None) or getattr(
                event.actor, "email", None
            )

        return {
            "uid": str(event.uid),
            "event_type": event.event_type,
            "title": event.event_type.replace("_", " ").title(),
            "company_uid": str(event.company.uid),
            "company_name": event.company.name,
            "previous_status": event.previous_status,
            "new_status": event.new_status,
            "source": event.source,
            "payload": event.payload,
            "actor_uid": str(event.actor.uid) if event.actor else None,
            "actor_name": actor_name,
            "created_at": event.created_at,
        }

    @classmethod
    def _category_filter(cls, category: str) -> Q:
        event_types = cls.CATEGORY_EVENT_TYPES.get(category.lower())
        if not event_types:
            return Q()

        base = Q(event_type__in=event_types)
        if category.lower() == "coupon":
            return base & (
                Q(payload__action="apply_coupon")
                | Q(payload__has_key="coupon_code")
                | Q(payload__coupon_uid__isnull=False)
            )
        return base

    @classmethod
    def get_events_queryset(
        cls,
        *,
        search: str | None = None,
        category: str | None = None,
    ):
        queryset = SubscriptionEvent.objects.select_related(
            "company", "actor", "company_subscription"
        ).order_by("-created_at")

        if category and category.lower() != "all":
            queryset = queryset.filter(cls._category_filter(category))

        if search:
            queryset = queryset.filter(
                Q(company__name__icontains=search)
                | Q(company__email__icontains=search)
                | Q(event_type__icontains=search)
                | Q(payload__icontains=search)
            )
        return queryset

    @classmethod
    def serialize_events(cls, events) -> list[dict[str, Any]]:
        return [cls._serialize_event(event) for event in events]

    @classmethod
    def list_events(
        cls,
        *,
        search: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        queryset = cls.get_events_queryset(search=search, category=category)
        limit = min(max(limit, 1), 200)
        events = queryset[:limit]
        return {
            "count": len(events),
            "results": cls.serialize_events(events),
        }
