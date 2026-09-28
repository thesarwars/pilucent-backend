from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.timezone import now

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    ScheduledPlanChangeKindChoices,
    ScheduledPlanChangeStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import ScheduledPlanChange, SubscriptionPrice
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.plan_change_guard_service import PlanChangeGuardService
from subscriptionio.services.plan_version_service import PlanVersionService
from subscriptionio.services.proration_service import ProrationService
from subscriptionio.services.subscription_event_service import SubscriptionEventService


class PlanChangeService:
    ACTIVE_STATUSES = {
        CompanySubscriptionStatusChoices.ACTIVE,
        CompanySubscriptionStatusChoices.TRIALING,
        CompanySubscriptionStatusChoices.PAST_DUE,
        CompanySubscriptionStatusChoices.GRACE,
    }

    @classmethod
    def _resolve_target_price(
        cls,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
    ) -> SubscriptionPrice | None:
        from subscriptionio.services.billing_preview_service import BillingPreviewService

        return BillingPreviewService._resolve_subscription_price(
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )

    @classmethod
    def _is_downgrade(
        cls,
        current_price: SubscriptionPrice,
        target_price: SubscriptionPrice,
    ) -> bool:
        current_amount = Decimal(current_price.price or 0)
        target_amount = Decimal(target_price.price or 0)
        if target_amount != current_amount:
            return target_amount < current_amount
        current_sub = current_price.subscription
        target_sub = target_price.subscription
        return (
            target_sub.employee_limit < current_sub.employee_limit
            or target_sub.user_limit < current_sub.user_limit
        )

    @classmethod
    def _serialize_scheduled_change(cls, change: ScheduledPlanChange) -> dict[str, Any]:
        target = change.target_subscription_price
        current = change.current_subscription_price
        return {
            "uid": str(change.uid),
            "status": change.status,
            "change_kind": change.change_kind,
            "scheduled_for": change.scheduled_for,
            "requires_usage_reduction": change.requires_usage_reduction,
            "notes": change.notes,
            "current_plan": {
                "uid": str(current.subscription.uid),
                "title": current.subscription.title,
                "price_uid": str(current.uid),
                "billing_frequency": current.billing_frequency,
            }
            if current
            else None,
            "target_plan": {
                "uid": str(target.subscription.uid),
                "title": target.subscription.title,
                "price_uid": str(target.uid),
                "billing_frequency": target.billing_frequency,
            },
        }

    @classmethod
    def get_scheduled_change(cls, company) -> dict[str, Any] | None:
        change = (
            ScheduledPlanChange.objects.filter(
                company=company,
                status=ScheduledPlanChangeStatusChoices.SCHEDULED,
            )
            .select_related(
                "current_subscription_price__subscription",
                "target_subscription_price__subscription",
            )
            .order_by("scheduled_for")
            .first()
        )
        if not change:
            return None
        return cls._serialize_scheduled_change(change)

    @classmethod
    def preview_plan_change(
        cls,
        company,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        immediate: bool = False,
    ) -> dict[str, Any]:
        target_price = cls._resolve_target_price(
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )
        if not target_price:
            raise ValueError("Subscription price not found.")

        company_subscription = EntitlementService.get_company_subscription(company)
        guard = PlanChangeGuardService.validate_plan_change(
            company,
            subscription_price=target_price,
        )
        proration = ProrationService.calculate_plan_change_proration(
            company,
            target_subscription_price=target_price,
        )

        is_downgrade = False
        if company_subscription:
            is_downgrade = cls._is_downgrade(
                company_subscription.subscription_price,
                target_price,
            )

        scheduled_for = None
        if company_subscription and is_downgrade and not immediate:
            scheduled_for = (
                company_subscription.current_period_end or company_subscription.renew_date
            )

        return {
            "allowed": guard.allowed,
            "message": guard.message,
            "blockers": guard.blockers,
            "is_downgrade": is_downgrade,
            "immediate": immediate,
            "scheduled_for": scheduled_for,
            "requires_usage_reduction": bool(guard.blockers),
            "proration": proration,
            "target_plan": {
                "uid": str(target_price.subscription.uid),
                "title": target_price.subscription.title,
                "price_uid": str(target_price.uid),
                "billing_frequency": target_price.billing_frequency,
                "price": str(target_price.price),
            },
        }

    @classmethod
    @transaction.atomic
    def schedule_downgrade(
        cls,
        company,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        notes: str = "",
        actor=None,
    ) -> dict[str, Any]:
        preview = cls.preview_plan_change(
            company,
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
            immediate=False,
        )
        if not preview["is_downgrade"]:
            raise ValueError("Only downgrades can be scheduled. Use checkout for upgrades.")

        target_price = cls._resolve_target_price(
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )
        if not target_price:
            raise ValueError("Subscription price not found.")

        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription or company_subscription.status not in cls.ACTIVE_STATUSES:
            raise ValueError("No active subscription to change.")

        scheduled_for = preview["scheduled_for"]
        if not scheduled_for:
            raise ValueError("Unable to determine the next billing period end.")

        ScheduledPlanChange.objects.filter(
            company=company,
            status=ScheduledPlanChangeStatusChoices.SCHEDULED,
        ).update(status=ScheduledPlanChangeStatusChoices.CANCELED, updated_at=now())

        change = ScheduledPlanChange.objects.create(
            company=company,
            company_subscription=company_subscription,
            current_subscription_price=company_subscription.subscription_price,
            target_subscription_price=target_price,
            scheduled_for=scheduled_for,
            change_kind=ScheduledPlanChangeKindChoices.DOWNGRADE,
            requires_usage_reduction=preview["requires_usage_reduction"],
            notes=notes,
        )

        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.DOWNGRADE_SCHEDULED,
            source=SubscriptionEventSourceChoices.API,
            actor=actor,
            payload={
                "scheduled_change_uid": str(change.uid),
                "target_plan_title": target_price.subscription.title,
                "scheduled_for": scheduled_for.isoformat(),
                "requires_usage_reduction": preview["requires_usage_reduction"],
                "blockers": preview["blockers"],
            },
        )
        return cls._serialize_scheduled_change(change)

    @classmethod
    @transaction.atomic
    def cancel_scheduled_change(cls, company, *, actor=None) -> dict[str, str]:
        change = (
            ScheduledPlanChange.objects.filter(
                company=company,
                status=ScheduledPlanChangeStatusChoices.SCHEDULED,
            )
            .select_related("company_subscription")
            .first()
        )
        if not change:
            raise ValueError("No scheduled plan change found.")

        change.status = ScheduledPlanChangeStatusChoices.CANCELED
        change.save(update_fields=["status", "updated_at"])
        SubscriptionEventService.record(
            company=company,
            company_subscription=change.company_subscription,
            event_type=SubscriptionEventTypeChoices.DOWNGRADE_CANCELED,
            source=SubscriptionEventSourceChoices.API,
            actor=actor,
            payload={"scheduled_change_uid": str(change.uid)},
        )
        return {"status": "canceled", "message": "Scheduled plan change canceled."}

    @classmethod
    @transaction.atomic
    def execute_scheduled_change(cls, change: ScheduledPlanChange) -> bool:
        if change.status != ScheduledPlanChangeStatusChoices.SCHEDULED:
            return False

        company = change.company
        guard = PlanChangeGuardService.validate_plan_change(
            company,
            subscription_price=change.target_subscription_price,
        )
        if not guard.allowed:
            return False

        company_subscription = change.company_subscription
        previous_status = company_subscription.status
        target_price = change.target_subscription_price
        plan_version = PlanVersionService.ensure_initial_version(target_price.subscription)

        company_subscription.subscription_price = target_price
        company_subscription.plan_version = plan_version
        company_subscription.save(
            update_fields=["subscription_price", "plan_version", "updated_at"]
        )

        change.status = ScheduledPlanChangeStatusChoices.COMPLETED
        change.save(update_fields=["status", "updated_at"])
        invalidate_entitlement_cache(company.id)

        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PLAN_CHANGE_EXECUTED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=SubscriptionEventSourceChoices.SYSTEM,
            payload={
                "scheduled_change_uid": str(change.uid),
                "change_kind": change.change_kind,
                "target_plan_title": target_price.subscription.title,
            },
        )
        return True

    @classmethod
    def execute_due_scheduled_changes(cls) -> int:
        due_changes = ScheduledPlanChange.objects.filter(
            status=ScheduledPlanChangeStatusChoices.SCHEDULED,
            scheduled_for__lte=now(),
        ).select_related(
            "company",
            "company_subscription",
            "target_subscription_price__subscription",
        )
        executed = 0
        for change in due_changes.iterator():
            if cls.execute_scheduled_change(change):
                executed += 1
        return executed
