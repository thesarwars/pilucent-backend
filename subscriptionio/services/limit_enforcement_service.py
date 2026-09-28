from dataclasses import dataclass, field
from typing import Any

from subscriptionio.choices import (
    LimitEnforcementModeChoices,
    LimitMetricChoices,
)
from subscriptionio.models import PlanLimit, UsageCounter
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.usage_service import UsageService


@dataclass
class LimitCheckResult:
    allowed: bool
    metric_code: str
    usage: int
    included_quantity: int | None
    enforcement_mode: str | None
    message: str = ""
    warning: str | None = None
    upgrade_metadata: dict[str, Any] = field(default_factory=dict)


class LimitEnforcementService:
    LIMIT_DENIED_MESSAGE = (
        "You have reached the limit for {metric} on your current plan. "
        "Please upgrade your subscription to add more."
    )
    LIMIT_WARNING_MESSAGE = (
        "You are over the included {metric} limit on your current plan. "
        "Overage charges may apply."
    )

    @classmethod
    def _metric_label(cls, metric_code: str) -> str:
        return {
            LimitMetricChoices.EMPLOYEE: "employees",
            LimitMetricChoices.USER: "users",
            LimitMetricChoices.BRANCH: "branches",
            LimitMetricChoices.STORAGE: "storage",
            LimitMetricChoices.PAYROLL_RUN: "payroll runs",
            LimitMetricChoices.AI_CREDIT: "AI credits",
        }.get(metric_code, metric_code.lower())

    @classmethod
    def _get_subscription_fallback_included(cls, subscription, metric_code: str) -> int:
        if metric_code == LimitMetricChoices.EMPLOYEE:
            return subscription.employee_limit or 0
        if metric_code == LimitMetricChoices.USER:
            return subscription.user_limit or 0
        if metric_code == LimitMetricChoices.STORAGE:
            return subscription.storage_limit or 0
        return 0

    @classmethod
    def _resolve_limit_config(cls, company, metric_code: str):
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            return None, None, None

        subscription = company_subscription.subscription_price.subscription
        plan_version = EntitlementService._ensure_plan_version(company_subscription)
        plan_limit = None
        if plan_version:
            plan_limit = plan_version.limits.filter(metric_code=metric_code).first()

        if plan_limit:
            return (
                plan_limit.included_quantity,
                plan_limit.enforcement_mode,
                plan_limit,
            )

        fallback = cls._get_subscription_fallback_included(subscription, metric_code)
        if fallback > 0:
            return fallback, LimitEnforcementModeChoices.SOFT_WARNING, None

        return None, None, None

    @classmethod
    def get_usage(cls, company, metric_code: str, *, use_counter: bool = True) -> int:
        if use_counter:
            counter = UsageCounter.objects.filter(
                company=company,
                metric_code=metric_code,
            ).first()
            if counter:
                return counter.quantity

        usage = UsageService.get_company_usage(company)
        return usage.get(metric_code, 0)

    @classmethod
    def check_limit(
        cls,
        company,
        metric_code: str,
        *,
        projected_usage: int | None = None,
    ) -> LimitCheckResult:
        included, enforcement_mode, plan_limit = cls._resolve_limit_config(
            company, metric_code
        )
        usage = (
            projected_usage
            if projected_usage is not None
            else cls.get_usage(company, metric_code)
        )

        if included is None or included <= 0:
            return LimitCheckResult(
                allowed=True,
                metric_code=metric_code,
                usage=usage,
                included_quantity=None,
                enforcement_mode=None,
            )

        over_limit = usage > included
        metric_label = cls._metric_label(metric_code)
        upgrade_metadata = {
            "metric": metric_code,
            "usage": usage,
            "included_quantity": included,
            "enforcement_mode": enforcement_mode,
        }
        if plan_limit and plan_limit.overage_unit_price:
            upgrade_metadata["overage_unit_price"] = str(plan_limit.overage_unit_price)

        if not over_limit:
            return LimitCheckResult(
                allowed=True,
                metric_code=metric_code,
                usage=usage,
                included_quantity=included,
                enforcement_mode=enforcement_mode,
            )

        if enforcement_mode == LimitEnforcementModeChoices.HARD_BLOCK:
            return LimitCheckResult(
                allowed=False,
                metric_code=metric_code,
                usage=usage,
                included_quantity=included,
                enforcement_mode=enforcement_mode,
                message=cls.LIMIT_DENIED_MESSAGE.format(metric=metric_label),
                upgrade_metadata=upgrade_metadata,
            )

        if enforcement_mode in {
            LimitEnforcementModeChoices.SOFT_WARNING,
            LimitEnforcementModeChoices.AUTO_OVERAGE,
            LimitEnforcementModeChoices.GRACE_OVERAGE,
        }:
            return LimitCheckResult(
                allowed=True,
                metric_code=metric_code,
                usage=usage,
                included_quantity=included,
                enforcement_mode=enforcement_mode,
                warning=cls.LIMIT_WARNING_MESSAGE.format(metric=metric_label),
                upgrade_metadata=upgrade_metadata,
            )

        return LimitCheckResult(
            allowed=True,
            metric_code=metric_code,
            usage=usage,
            included_quantity=included,
            enforcement_mode=enforcement_mode,
            warning=cls.LIMIT_WARNING_MESSAGE.format(metric=metric_label),
            upgrade_metadata=upgrade_metadata,
        )

    @classmethod
    def check_create_allowed(cls, company, metric_code: str) -> LimitCheckResult:
        current_usage = cls.get_usage(company, metric_code)
        return cls.check_limit(
            company,
            metric_code,
            projected_usage=current_usage + 1,
        )

    @classmethod
    def get_company_limit_status(cls, company) -> dict[str, dict[str, Any]]:
        metrics = [
            LimitMetricChoices.EMPLOYEE,
            LimitMetricChoices.USER,
        ]
        payload = {}
        for metric_code in metrics:
            result = cls.check_limit(company, metric_code)
            payload[metric_code] = {
                "usage": result.usage,
                "included_quantity": result.included_quantity,
                "enforcement_mode": result.enforcement_mode,
                "allowed": result.allowed,
                "warning": result.warning,
            }
        return payload
