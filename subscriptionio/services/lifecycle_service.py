import logging
from dataclasses import dataclass
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction
from django.utils.timezone import now

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.subscription_event_service import SubscriptionEventService

logger = logging.getLogger("subscriptionio.lifecycle")
stripe.api_key = settings.STRIPE_SECRET_KEY


@dataclass
class LifecycleActionResult:
    success: bool
    status: str | None = None
    message: str = ""
    cancel_at_period_end: bool = False
    current_period_end: str | None = None
    retention_offers: list[dict[str, Any]] | None = None


class LifecycleService:
    CANCELABLE_STATUSES = {
        CompanySubscriptionStatusChoices.ACTIVE,
        CompanySubscriptionStatusChoices.TRIALING,
        CompanySubscriptionStatusChoices.PAST_DUE,
        CompanySubscriptionStatusChoices.GRACE,
    }
    REACTIVATABLE_STATUSES = {
        CompanySubscriptionStatusChoices.CANCELED,
        CompanySubscriptionStatusChoices.PAST_DUE,
        CompanySubscriptionStatusChoices.SUSPENDED,
    }

    @classmethod
    def get_lifecycle_state(cls, company) -> dict:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            return {
                "has_subscription": False,
                "status": None,
                "cancel_at_period_end": False,
                "canceled_at": None,
                "dunning_started_at": None,
                "grace_ends_at": None,
                "suspend_ends_at": None,
                "failed_payment_count": 0,
            }

        return {
            "has_subscription": True,
            "status": company_subscription.status,
            "cancel_at_period_end": company_subscription.cancel_at_period_end,
            "canceled_at": company_subscription.canceled_at,
            "dunning_started_at": company_subscription.dunning_started_at,
            "grace_ends_at": company_subscription.grace_ends_at,
            "suspend_ends_at": company_subscription.suspend_ends_at,
            "failed_payment_count": company_subscription.failed_payment_count,
            "current_period_end": company_subscription.current_period_end,
        }

    @classmethod
    @transaction.atomic
    def cancel_subscription(
        cls,
        company,
        *,
        at_period_end: bool = True,
        actor=None,
        reason: str = "",
    ) -> LifecycleActionResult:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            return LifecycleActionResult(success=False, message="No subscription found.")

        if company_subscription.status not in cls.CANCELABLE_STATUSES:
            return LifecycleActionResult(
                success=False,
                status=company_subscription.status,
                message="Subscription cannot be canceled in its current state.",
            )

        previous_status = company_subscription.status
        stripe_subscription_id = company_subscription.stripe_subscription_id

        if stripe_subscription_id:
            try:
                if at_period_end:
                    stripe.Subscription.modify(
                        stripe_subscription_id,
                        cancel_at_period_end=True,
                    )
                    company_subscription.cancel_at_period_end = True
                else:
                    stripe.Subscription.cancel(stripe_subscription_id)
                    company_subscription.status = CompanySubscriptionStatusChoices.CANCELED
                    company_subscription.canceled_at = now()
                    company_subscription.cancel_at_period_end = False
            except stripe.error.StripeError as exc:
                logger.exception("Stripe cancel failed for company=%s", company.uid)
                return LifecycleActionResult(
                    success=False,
                    message=f"Unable to cancel subscription: {exc.user_message if hasattr(exc, 'user_message') else str(exc)}",
                )
        else:
            company_subscription.status = CompanySubscriptionStatusChoices.CANCELED
            company_subscription.canceled_at = now()
            company_subscription.cancel_at_period_end = False

        if at_period_end and stripe_subscription_id:
            company_subscription.save(
                update_fields=["cancel_at_period_end", "updated_at"]
            )
        else:
            company_subscription.save(
                update_fields=[
                    "status",
                    "canceled_at",
                    "cancel_at_period_end",
                    "updated_at",
                ]
            )

        invalidate_entitlement_cache(company.id)
        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.SUBSCRIPTION_CANCELED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=SubscriptionEventSourceChoices.API,
            actor=actor,
            payload={"at_period_end": at_period_end, "reason": reason},
        )

        from subscriptionio.services.offer_service import OfferService

        retention_offers = OfferService.get_retention_offers(company)

        return LifecycleActionResult(
            success=True,
            status=company_subscription.status,
            cancel_at_period_end=company_subscription.cancel_at_period_end,
            current_period_end=(
                company_subscription.current_period_end.isoformat()
                if company_subscription.current_period_end
                else None
            ),
            retention_offers=retention_offers,
            message=(
                "Subscription will cancel at the end of the billing period."
                if at_period_end
                else "Subscription canceled immediately."
            ),
        )

    @classmethod
    @transaction.atomic
    def reactivate_subscription(
        cls,
        company,
        *,
        actor=None,
    ) -> LifecycleActionResult:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            return LifecycleActionResult(success=False, message="No subscription found.")

        if (
            company_subscription.status not in cls.REACTIVATABLE_STATUSES
            and not company_subscription.cancel_at_period_end
        ):
            return LifecycleActionResult(
                success=False,
                status=company_subscription.status,
                message="Subscription cannot be reactivated in its current state.",
            )

        previous_status = company_subscription.status
        stripe_subscription_id = company_subscription.stripe_subscription_id

        if stripe_subscription_id:
            try:
                stripe.Subscription.modify(
                    stripe_subscription_id,
                    cancel_at_period_end=False,
                )
            except stripe.error.StripeError as exc:
                logger.exception("Stripe reactivate failed for company=%s", company.uid)
                return LifecycleActionResult(
                    success=False,
                    message=f"Unable to reactivate subscription: {exc.user_message if hasattr(exc, 'user_message') else str(exc)}",
                )

        company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        company_subscription.cancel_at_period_end = False
        company_subscription.canceled_at = None
        company_subscription.save(
            update_fields=[
                "status",
                "cancel_at_period_end",
                "canceled_at",
                "updated_at",
            ]
        )
        invalidate_entitlement_cache(company.id)
        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.SUBSCRIPTION_REACTIVATED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=SubscriptionEventSourceChoices.API,
            actor=actor,
        )

        return LifecycleActionResult(
            success=True,
            status=company_subscription.status,
            message="Subscription reactivated.",
        )
