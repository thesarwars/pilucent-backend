from datetime import timedelta

from django.db import transaction
from django.utils.timezone import now

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import CompanySubscription
from subscriptionio.services.subscription_event_service import SubscriptionEventService

PAST_DUE_TO_GRACE_DAYS = 3
GRACE_PERIOD_DAYS = 7
SUSPEND_PERIOD_DAYS = 14


class DunningService:
    @classmethod
    def _clear_dunning_fields(cls, company_subscription: CompanySubscription):
        company_subscription.dunning_started_at = None
        company_subscription.grace_ends_at = None
        company_subscription.suspend_ends_at = None
        company_subscription.failed_payment_count = 0

    @classmethod
    @transaction.atomic
    def record_payment_failure(
        cls,
        company_subscription: CompanySubscription,
        *,
        source: str = SubscriptionEventSourceChoices.WEBHOOK,
        payload: dict | None = None,
    ):
        previous_status = company_subscription.status
        company_subscription.status = CompanySubscriptionStatusChoices.PAST_DUE
        company_subscription.failed_payment_count += 1
        if not company_subscription.dunning_started_at:
            company_subscription.dunning_started_at = now()

        company_subscription.save(
            update_fields=[
                "status",
                "failed_payment_count",
                "dunning_started_at",
                "updated_at",
            ]
        )
        invalidate_entitlement_cache(company_subscription.company_id)
        SubscriptionEventService.record(
            company=company_subscription.company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PAYMENT_FAILED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=source,
            payload={
                "failed_payment_count": company_subscription.failed_payment_count,
                **(payload or {}),
            },
        )

    @classmethod
    @transaction.atomic
    def record_payment_recovery(
        cls,
        company_subscription: CompanySubscription,
        *,
        source: str = SubscriptionEventSourceChoices.WEBHOOK,
        payload: dict | None = None,
    ):
        previous_status = company_subscription.status
        company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        cls._clear_dunning_fields(company_subscription)
        company_subscription.save(
            update_fields=[
                "status",
                "dunning_started_at",
                "grace_ends_at",
                "suspend_ends_at",
                "failed_payment_count",
                "updated_at",
            ]
        )
        invalidate_entitlement_cache(company_subscription.company_id)
        SubscriptionEventService.record(
            company=company_subscription.company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PAYMENT_RECOVERED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=source,
            payload=payload or {},
        )

    @classmethod
    @transaction.atomic
    def process_dunning(cls) -> dict[str, int]:
        current = now()
        stats = {"grace": 0, "suspended": 0, "expired": 0}

        past_due_qs = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.PAST_DUE,
            dunning_started_at__isnull=False,
            dunning_started_at__lte=current - timedelta(days=PAST_DUE_TO_GRACE_DAYS),
        )
        for company_subscription in past_due_qs.iterator():
            previous_status = company_subscription.status
            company_subscription.status = CompanySubscriptionStatusChoices.GRACE
            company_subscription.grace_ends_at = current + timedelta(days=GRACE_PERIOD_DAYS)
            company_subscription.save(
                update_fields=["status", "grace_ends_at", "updated_at"]
            )
            invalidate_entitlement_cache(company_subscription.company_id)
            SubscriptionEventService.record(
                company=company_subscription.company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.DUNNING_GRACE,
                previous_status=previous_status,
                new_status=company_subscription.status,
                payload={"grace_ends_at": company_subscription.grace_ends_at.isoformat()},
            )
            stats["grace"] += 1

        grace_qs = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.GRACE,
            grace_ends_at__isnull=False,
            grace_ends_at__lt=current,
        )
        for company_subscription in grace_qs.iterator():
            previous_status = company_subscription.status
            company_subscription.status = CompanySubscriptionStatusChoices.SUSPENDED
            company_subscription.suspend_ends_at = current + timedelta(
                days=SUSPEND_PERIOD_DAYS
            )
            company_subscription.save(
                update_fields=["status", "suspend_ends_at", "updated_at"]
            )
            invalidate_entitlement_cache(company_subscription.company_id)
            SubscriptionEventService.record(
                company=company_subscription.company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.DUNNING_SUSPENDED,
                previous_status=previous_status,
                new_status=company_subscription.status,
                payload={
                    "suspend_ends_at": company_subscription.suspend_ends_at.isoformat()
                },
            )
            stats["suspended"] += 1

        suspended_qs = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.SUSPENDED,
            suspend_ends_at__isnull=False,
            suspend_ends_at__lt=current,
        )
        for company_subscription in suspended_qs.iterator():
            previous_status = company_subscription.status
            company_subscription.status = CompanySubscriptionStatusChoices.EXPIRED
            company_subscription.save(update_fields=["status", "updated_at"])
            invalidate_entitlement_cache(company_subscription.company_id)
            SubscriptionEventService.record(
                company=company_subscription.company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.DUNNING_EXPIRED,
                previous_status=previous_status,
                new_status=company_subscription.status,
            )
            stats["expired"] += 1

        return stats
