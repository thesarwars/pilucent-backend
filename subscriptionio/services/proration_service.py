from decimal import Decimal
from typing import Any

from django.utils.timezone import now

from subscriptionio.models import SubscriptionPrice
from subscriptionio.services.analytics_service import SubscriptionAnalyticsService
from subscriptionio.services.entitlement_service import EntitlementService


class ProrationService:
    @classmethod
    def _period_fraction(cls, company_subscription, *, as_of=None) -> Decimal:
        as_of = as_of or now()
        period_start = company_subscription.current_period_start or company_subscription.start_date
        period_end = (
            company_subscription.current_period_end or company_subscription.renew_date
        )
        if not period_start or not period_end or period_end <= period_start:
            return Decimal("0")

        total_seconds = Decimal(str((period_end - period_start).total_seconds()))
        remaining_seconds = Decimal(str(max(0, (period_end - as_of).total_seconds())))
        if total_seconds <= 0:
            return Decimal("0")
        return min(Decimal("1"), remaining_seconds / total_seconds)

    @classmethod
    def _normalize_period_amount(cls, subscription_price: SubscriptionPrice) -> Decimal:
        return SubscriptionAnalyticsService._normalize_to_mrr(
            Decimal(subscription_price.price or 0),
            subscription_price.billing_frequency,
        )

    @classmethod
    def calculate_plan_change_proration(
        cls,
        company,
        *,
        target_subscription_price: SubscriptionPrice,
        current_subscription_price: SubscriptionPrice | None = None,
    ) -> dict[str, Any]:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            return {
                "applies": False,
                "proration_amount": "0",
                "remaining_fraction": "0",
                "current_period_amount": "0",
                "target_period_amount": "0",
            }

        current_subscription_price = (
            current_subscription_price or company_subscription.subscription_price
        )
        fraction = cls._period_fraction(company_subscription)
        current_amount = cls._normalize_period_amount(current_subscription_price)
        target_amount = cls._normalize_period_amount(target_subscription_price)
        proration_amount = (target_amount - current_amount) * fraction

        return {
            "applies": fraction > 0,
            "proration_amount": str(proration_amount.quantize(Decimal("0.01"))),
            "remaining_fraction": str(fraction.quantize(Decimal("0.0001"))),
            "current_period_amount": str(current_amount.quantize(Decimal("0.01"))),
            "target_period_amount": str(target_amount.quantize(Decimal("0.01"))),
            "period_start": company_subscription.current_period_start
            or company_subscription.start_date,
            "period_end": company_subscription.current_period_end
            or company_subscription.renew_date,
        }
