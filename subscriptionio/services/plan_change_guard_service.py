from dataclasses import dataclass, field
from typing import Any

from subscriptionio.choices import LimitMetricChoices
from subscriptionio.models import SubscriptionPrice
from subscriptionio.services.billing_preview_service import BillingPreviewService
from subscriptionio.services.limit_enforcement_service import LimitEnforcementService
from subscriptionio.services.usage_service import UsageService


@dataclass
class PlanChangeGuardResult:
    allowed: bool
    message: str = ""
    blockers: list[dict[str, Any]] = field(default_factory=list)


class PlanChangeGuardService:
    DOWNGRADE_BLOCKED_MESSAGE = (
        "This plan change is not allowed because your current usage exceeds "
        "the target plan limits."
    )

    @classmethod
    def _resolve_subscription_price(
        cls,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
    ):
        return BillingPreviewService._resolve_subscription_price(
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )

    @classmethod
    def _target_included(cls, preview, metric_code: str) -> int | None:
        limit_data = preview.limits.get(metric_code)
        if limit_data and limit_data.get("included_quantity") is not None:
            return int(limit_data["included_quantity"])

        subscription_price = BillingPreviewService._resolve_subscription_price(
            plan_title=preview.plan_title,
            billing_frequency=preview.billing_frequency,
        )
        if not subscription_price:
            return None

        subscription = subscription_price.subscription
        if metric_code == LimitMetricChoices.EMPLOYEE:
            return subscription.employee_limit or None
        if metric_code == LimitMetricChoices.USER:
            return subscription.user_limit or None
        return None

    @classmethod
    def validate_plan_change(
        cls,
        company,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
    ) -> PlanChangeGuardResult:
        preview = BillingPreviewService.preview(
            company,
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )
        if not preview:
            return PlanChangeGuardResult(
                allowed=False,
                message="Subscription price not found.",
            )

        usage = UsageService.get_company_usage(company)
        blockers = []

        for metric_code in (LimitMetricChoices.EMPLOYEE, LimitMetricChoices.USER):
            included = cls._target_included(preview, metric_code)
            current_usage = usage.get(metric_code, 0)
            if included is not None and included > 0 and current_usage > included:
                blockers.append(
                    {
                        "metric": metric_code,
                        "usage": current_usage,
                        "included_quantity": included,
                    }
                )

        if blockers:
            return PlanChangeGuardResult(
                allowed=False,
                message=cls.DOWNGRADE_BLOCKED_MESSAGE,
                blockers=blockers,
            )

        return PlanChangeGuardResult(allowed=True)
