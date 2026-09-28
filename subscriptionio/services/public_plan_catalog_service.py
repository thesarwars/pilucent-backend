from decimal import Decimal
from typing import Any

from common.choices import DiscountKind

from subscriptionio.choices import (
    LimitMetricChoices,
    PlanVersionStatusChoices,
    SubscriptionStatusChoices,
)
from subscriptionio.models import PlanVersion, Subscription, SubscriptionPrice


class PublicPlanCatalogService:
    @classmethod
    def _serialize_prices(cls, subscription: Subscription, *, currency: str | None = None) -> list[dict]:
        prices_qs = SubscriptionPrice.objects.filter(
            subscription=subscription,
            is_active=True,
        ).order_by("billing_frequency", "currency")
        if currency:
            prices_qs = prices_qs.filter(currency=currency)

        return [
            {
                "uid": str(price.uid),
                "slug": price.slug,
                "billing_frequency": price.billing_frequency,
                "price": str(price.price),
                "currency": price.currency,
                "discount": str(price.discount or 0),
                "discount_kind": price.discount_kind,
            }
            for price in prices_qs
        ]

    @classmethod
    def _serialize_published_version(cls, plan_version: PlanVersion | None) -> dict | None:
        if not plan_version:
            return None

        features = []
        for plan_feature in plan_version.plan_features.select_related("feature").all():
            if not plan_feature.is_enabled:
                continue
            features.append(
                {
                    "code": plan_feature.feature.code,
                    "access_level": plan_feature.access_level,
                    "limit_value": plan_feature.limit_value,
                }
            )

        limits = [
            {
                "metric_code": plan_limit.metric_code,
                "included_quantity": plan_limit.included_quantity,
                "overage_unit_price": str(plan_limit.overage_unit_price),
                "enforcement_mode": plan_limit.enforcement_mode,
            }
            for plan_limit in plan_version.limits.all()
        ]

        return {
            "uid": str(plan_version.uid),
            "version_no": plan_version.version_no,
            "features": features,
            "limits": limits,
        }

    @classmethod
    def _get_published_version(cls, subscription: Subscription) -> PlanVersion | None:
        return (
            PlanVersion.objects.filter(
                subscription=subscription,
                status=PlanVersionStatusChoices.PUBLISHED,
            )
            .prefetch_related("limits", "plan_features__feature")
            .order_by("-version_no")
            .first()
        )

    @classmethod
    def _serialize_plan(
        cls,
        subscription: Subscription,
        *,
        currency: str | None = None,
    ) -> dict[str, Any]:
        published_version = cls._get_published_version(subscription)
        prices = cls._serialize_prices(subscription, currency=currency)

        return {
            "uid": str(subscription.uid),
            "slug": subscription.slug,
            "title": subscription.title,
            "description": subscription.description,
            "currency": subscription.currency,
            "trial_period": subscription.trial_period,
            "employee_limit": subscription.employee_limit,
            "user_limit": subscription.user_limit,
            "prices": prices,
            "published_version": cls._serialize_published_version(published_version),
        }

    @classmethod
    def list_plans(cls, *, currency: str | None = None, kind: str | None = None) -> list[dict]:
        queryset = Subscription.objects.filter(
            status=SubscriptionStatusChoices.PUBLISHED,
        ).order_by("title")
        if kind:
            queryset = queryset.filter(kind=kind)
        return [cls._serialize_plan(sub, currency=currency) for sub in queryset]

    @classmethod
    def get_plan(cls, *, slug: str, currency: str | None = None) -> dict | None:
        subscription = Subscription.objects.filter(
            slug=slug,
            status=SubscriptionStatusChoices.PUBLISHED,
        ).first()
        if not subscription:
            return None
        return cls._serialize_plan(subscription, currency=currency)

    @classmethod
    def quote_preview(
        cls,
        *,
        subscription_price_slug: str | None = None,
        plan_slug: str | None = None,
        billing_frequency: str | None = None,
        currency: str | None = None,
        employee_count: int = 0,
        user_count: int = 0,
    ) -> dict[str, Any] | None:
        subscription_price = None
        if subscription_price_slug:
            subscription_price = SubscriptionPrice.objects.select_related(
                "subscription"
            ).filter(slug=subscription_price_slug, is_active=True).first()
        elif plan_slug and billing_frequency:
            subscription_price = SubscriptionPrice.objects.select_related(
                "subscription"
            ).filter(
                subscription__slug=plan_slug,
                subscription__status=SubscriptionStatusChoices.PUBLISHED,
                billing_frequency=billing_frequency,
                is_active=True,
            ).first()
            if currency:
                subscription_price = SubscriptionPrice.objects.select_related(
                    "subscription"
                ).filter(
                    subscription__slug=plan_slug,
                    subscription__status=SubscriptionStatusChoices.PUBLISHED,
                    billing_frequency=billing_frequency,
                    currency=currency,
                    is_active=True,
                ).first()

        if not subscription_price:
            return None

        subscription = subscription_price.subscription
        plan_version = cls._get_published_version(subscription)

        base_amount = Decimal(subscription_price.price or 0)
        discount_amount = Decimal("0")
        discount_value = Decimal(subscription_price.discount or 0)
        if discount_value > 0:
            if subscription_price.discount_kind == DiscountKind.PERCENTAGE:
                discount_amount = (base_amount * discount_value) / Decimal("100")
            else:
                discount_amount = discount_value
            discount_amount = min(discount_amount, base_amount)

        lines = [
            {
                "line_type": "BASE",
                "description": f"{subscription.title} ({subscription_price.billing_frequency})",
                "amount": str(base_amount),
            }
        ]
        if discount_amount > 0:
            lines.append(
                {
                    "line_type": "DISCOUNT",
                    "description": "Plan discount",
                    "amount": str(-discount_amount),
                }
            )

        overage_total = Decimal("0")

        def add_overage(metric_code: str, label: str, count: int, fallback_included: int):
            nonlocal overage_total
            included = fallback_included
            unit_price = Decimal("0")
            if plan_version:
                plan_limit = plan_version.limits.filter(metric_code=metric_code).first()
                if plan_limit:
                    included = plan_limit.included_quantity
                    unit_price = Decimal(plan_limit.overage_unit_price or 0)
            overage_units = max(0, count - included)
            if overage_units <= 0 or unit_price <= 0:
                return
            amount = Decimal(overage_units) * unit_price
            overage_total += amount
            lines.append(
                {
                    "line_type": "OVERAGE",
                    "description": f"{label} overage ({overage_units} x {unit_price})",
                    "amount": str(amount),
                    "metadata": {
                        "metric_code": metric_code,
                        "included_quantity": included,
                        "usage_count": count,
                    },
                }
            )

        add_overage(
            LimitMetricChoices.EMPLOYEE,
            "Employee",
            employee_count,
            subscription.employee_limit,
        )
        add_overage(
            LimitMetricChoices.USER,
            "User",
            user_count,
            subscription.user_limit,
        )

        subtotal = base_amount - discount_amount + overage_total
        return {
            "subscription_price_uid": str(subscription_price.uid),
            "plan_slug": subscription.slug,
            "plan_title": subscription.title,
            "billing_frequency": subscription_price.billing_frequency,
            "currency": subscription_price.currency,
            "usage": {
                LimitMetricChoices.EMPLOYEE: employee_count,
                LimitMetricChoices.USER: user_count,
            },
            "lines": lines,
            "subtotal": str(base_amount.quantize(Decimal("0.01"))),
            "discount_total": str(discount_amount.quantize(Decimal("0.01"))),
            "overage_total": str(overage_total.quantize(Decimal("0.01"))),
            "total": str(subtotal.quantize(Decimal("0.01"))),
        }
