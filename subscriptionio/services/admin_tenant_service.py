from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Count, Q
from django.utils.timezone import now

from companyio.models import Company

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    LimitMetricChoices,
    SubscriptionCreditSourceChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import (
    CompanySubscription,
    PlanVersion,
    SubscriptionCredit,
    SubscriptionPrice,
)
from subscriptionio.services.analytics_service import SubscriptionAnalyticsService
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.lifecycle_service import LifecycleService
from subscriptionio.services.limit_enforcement_service import LimitEnforcementService
from subscriptionio.services.subscription_billing_service import SubscriptionBillingService
from subscriptionio.services.subscription_event_service import SubscriptionEventService
from subscriptionio.services.trial_service import TrialService
from subscriptionio.services.usage_service import UsageService


class AdminTenantService:
    @classmethod
    def _base_queryset(cls):
        return CompanySubscription.objects.filter(
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
        ).select_related(
            "company",
            "subscription_price__subscription",
            "plan_version",
        )

    @classmethod
    def _mrr_for_subscription(cls, company_subscription: CompanySubscription) -> Decimal:
        subscription_price = company_subscription.subscription_price
        if company_subscription.status not in {
            CompanySubscriptionStatusChoices.ACTIVE,
            CompanySubscriptionStatusChoices.GRACE,
            CompanySubscriptionStatusChoices.PAST_DUE,
        }:
            return Decimal("0")
        return SubscriptionAnalyticsService._normalize_to_mrr(
            Decimal(subscription_price.price or 0),
            subscription_price.billing_frequency,
        )

    @classmethod
    def _serialize_tenant_row(cls, company_subscription: CompanySubscription) -> dict[str, Any]:
        company = company_subscription.company
        subscription_price = company_subscription.subscription_price
        subscription = subscription_price.subscription
        usage = UsageService.get_company_usage(company)
        limits = LimitEnforcementService.get_company_limit_status(company)
        employee_limit = limits.get(LimitMetricChoices.EMPLOYEE, {}).get("included_quantity")
        user_limit = limits.get(LimitMetricChoices.USER, {}).get("included_quantity")

        return {
            "company_uid": str(company.uid),
            "company_name": company.name,
            "company_email": company.email,
            "currency": subscription.currency,
            "plan_uid": str(subscription.uid),
            "plan_title": subscription.title,
            "status": company_subscription.status,
            "employee_count": usage.get(LimitMetricChoices.EMPLOYEE, 0),
            "employee_limit": employee_limit,
            "user_count": usage.get(LimitMetricChoices.USER, 0),
            "user_limit": user_limit,
            "mrr": str(cls._mrr_for_subscription(company_subscription).quantize(Decimal("0.01"))),
            "renewal_date": company_subscription.current_period_end
            or company_subscription.renew_date,
            "subscription_uid": str(company_subscription.uid),
        }

    @classmethod
    def get_tenants_queryset(
        cls,
        *,
        search: str | None = None,
        status: str | None = None,
        plan_uid: str | None = None,
    ):
        qs = cls._base_queryset().order_by("-updated_at")
        if search:
            qs = qs.filter(
                Q(company__name__icontains=search)
                | Q(company__email__icontains=search)
                | Q(company__legal_name__icontains=search)
            )
        if status:
            qs = qs.filter(status=status)
        if plan_uid:
            qs = qs.filter(subscription_price__subscription__uid=plan_uid)
        return qs

    @classmethod
    def serialize_tenant_rows(cls, company_subscriptions) -> list[dict[str, Any]]:
        return [cls._serialize_tenant_row(item) for item in company_subscriptions]

    @classmethod
    def list_tenants(
        cls,
        *,
        search: str | None = None,
        status: str | None = None,
        plan_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        return cls.serialize_tenant_rows(
            cls.get_tenants_queryset(
                search=search,
                status=status,
                plan_uid=plan_uid,
            )
        )

    @classmethod
    def get_tenant_detail(cls, company: Company) -> dict[str, Any]:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            return {
                "company_uid": str(company.uid),
                "company_name": company.name,
                "has_subscription": False,
            }

        billing = SubscriptionBillingService.get_current_subscription_payload(company)
        lifecycle = billing.get("lifecycle") or {}
        row = cls._serialize_tenant_row(company_subscription)

        return {
            **row,
            "has_subscription": True,
            "billing": billing,
            "lifecycle": lifecycle,
            "stripe_customer_id": company_subscription.stripe_customer_id,
            "stripe_subscription_id": company_subscription.stripe_subscription_id,
            "plan_version_uid": (
                str(company_subscription.plan_version.uid)
                if company_subscription.plan_version_id
                else None
            ),
            "trial_start": company_subscription.trial_start,
            "trial_end": company_subscription.trial_end,
            "cancel_at_period_end": company_subscription.cancel_at_period_end,
            "canceled_at": company_subscription.canceled_at,
        }

    @classmethod
    def get_tenant_events(cls, company: Company, *, limit: int = 50) -> list[dict[str, Any]]:
        return SubscriptionEventService.get_company_timeline(company, limit=limit)

    @classmethod
    @transaction.atomic
    def apply_action(
        cls,
        company: Company,
        *,
        action: str,
        actor=None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription and action not in {"apply_credit"}:
            raise ValueError("Company has no active company subscription.")

        if action == "override_plan":
            return cls._override_plan(company, company_subscription, payload, actor)
        if action == "apply_credit":
            return cls._apply_credit(company, payload, actor)
        if action == "extend_period":
            return cls._extend_period(company_subscription, payload, actor)
        if action == "extend_trial":
            return cls._extend_trial(company, payload)
        if action == "suspend":
            return cls._suspend(company, company_subscription, payload, actor)
        if action == "reactivate":
            return cls._reactivate(company, actor)
        raise ValueError(f"Unsupported action: {action}")

    @classmethod
    def _record_admin_event(
        cls,
        *,
        company,
        company_subscription,
        event_type: str,
        previous_status: str | None,
        new_status: str | None,
        actor,
        payload: dict,
    ):
        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            source=SubscriptionEventSourceChoices.ADMIN,
            actor=actor,
            payload=payload,
        )

    @classmethod
    def _override_plan(cls, company, company_subscription, payload, actor):
        subscription_price_uid = payload.get("subscription_price_uid")
        plan_version_uid = payload.get("plan_version_uid")
        if not subscription_price_uid:
            raise ValueError("subscription_price_uid is required.")

        subscription_price = SubscriptionPrice.objects.select_related("subscription").get(
            uid=subscription_price_uid
        )
        plan_version = None
        if plan_version_uid:
            plan_version = PlanVersion.objects.get(uid=plan_version_uid)

        previous_status = company_subscription.status
        company_subscription.subscription_price = subscription_price
        company_subscription.plan_version = plan_version
        if company_subscription.status in {
            CompanySubscriptionStatusChoices.PENDING,
            CompanySubscriptionStatusChoices.DRAFT,
        }:
            company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        company_subscription.save(
            update_fields=[
                "subscription_price",
                "plan_version",
                "status",
                "updated_at",
            ]
        )
        invalidate_entitlement_cache(company.id)
        cls._record_admin_event(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            actor=actor,
            payload={
                "action": "override_plan",
                "subscription_price_uid": str(subscription_price.uid),
                "plan_version_uid": str(plan_version.uid) if plan_version else None,
                "reason": payload.get("reason", ""),
            },
        )
        return cls.get_tenant_detail(company)

    @classmethod
    def _apply_credit(cls, company, payload, actor):
        amount = Decimal(str(payload.get("amount", "0")))
        if amount <= 0:
            raise ValueError("amount must be greater than zero.")

        credit = SubscriptionCredit.objects.create(
            company=company,
            initial_amount=amount,
            balance=amount,
            source=SubscriptionCreditSourceChoices.ADMIN_ADJUSTMENT,
            source_ref=payload.get("reason", "admin_adjustment"),
        )
        company_subscription = EntitlementService.get_company_subscription(company)
        if company_subscription:
            cls._record_admin_event(
                company=company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
                previous_status=company_subscription.status,
                new_status=company_subscription.status,
                actor=actor,
                payload={
                    "action": "apply_credit",
                    "credit_uid": str(credit.uid),
                    "amount": str(amount),
                    "reason": payload.get("reason", ""),
                },
            )
        return {
            "credit_uid": str(credit.uid),
            "amount": str(amount),
            "balance": str(credit.balance),
        }

    @classmethod
    def _extend_period(cls, company_subscription, payload, actor):
        days = int(payload.get("days", 0))
        if days <= 0:
            raise ValueError("days must be greater than zero.")

        previous_end = company_subscription.current_period_end or company_subscription.renew_date
        if not previous_end:
            previous_end = now()
        new_end = previous_end + timedelta(days=days)
        company_subscription.current_period_end = new_end
        company_subscription.renew_date = new_end
        company_subscription.save(
            update_fields=["current_period_end", "renew_date", "updated_at"]
        )
        invalidate_entitlement_cache(company_subscription.company_id)
        cls._record_admin_event(
            company=company_subscription.company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
            previous_status=company_subscription.status,
            new_status=company_subscription.status,
            actor=actor,
            payload={
                "action": "extend_period",
                "days": days,
                "new_period_end": new_end.isoformat(),
                "reason": payload.get("reason", ""),
            },
        )
        return cls.get_tenant_detail(company_subscription.company)

    @classmethod
    def _extend_trial(cls, company, payload):
        days = int(payload.get("days", 7))
        result = TrialService.extend_trial(company, extra_days=days)
        if not result.active and result.message:
            raise ValueError(result.message)
        return {
            "trial_end": result.trial_end,
            "days_remaining": result.days_remaining,
            "status": result.status,
        }

    @classmethod
    def _suspend(cls, company, company_subscription, payload, actor):
        previous_status = company_subscription.status
        company_subscription.status = CompanySubscriptionStatusChoices.SUSPENDED
        company_subscription.suspend_ends_at = now() + timedelta(days=30)
        company_subscription.save(
            update_fields=["status", "suspend_ends_at", "updated_at"]
        )
        invalidate_entitlement_cache(company.id)
        cls._record_admin_event(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.DUNNING_SUSPENDED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            actor=actor,
            payload={
                "action": "suspend",
                "reason": payload.get("reason", ""),
            },
        )
        return cls.get_tenant_detail(company)

    @classmethod
    def _reactivate(cls, company, actor):
        result = LifecycleService.reactivate_subscription(company, actor=actor)
        if not result.success:
            raise ValueError(result.message)
        return cls.get_tenant_detail(company)
