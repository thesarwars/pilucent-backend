from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils.timezone import now

from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    SubscriptionInvoiceLineTypeChoices,
    SubscriptionInvoiceStatusChoices,
    SubscriptionPriceBillingFrequencyChoices,
)
from subscriptionio.models import CompanySubscription, SubscriptionInvoice, SubscriptionInvoiceLine


class SubscriptionAnalyticsService:
    @classmethod
    def _monthly_multiplier(cls, billing_frequency: str) -> Decimal:
        mapping = {
            SubscriptionPriceBillingFrequencyChoices.WEEKLY: Decimal("52") / Decimal("12"),
            SubscriptionPriceBillingFrequencyChoices.MONTHLY: Decimal("1"),
            SubscriptionPriceBillingFrequencyChoices.QUARTERLY: Decimal("1") / Decimal("3"),
            SubscriptionPriceBillingFrequencyChoices.HALF_YEARLY: Decimal("1") / Decimal("6"),
            SubscriptionPriceBillingFrequencyChoices.YEARLY: Decimal("1") / Decimal("12"),
        }
        return mapping.get(billing_frequency, Decimal("1"))

    @classmethod
    def _normalize_to_mrr(cls, price: Decimal, billing_frequency: str) -> Decimal:
        return (price or Decimal("0")) * cls._monthly_multiplier(billing_frequency)

    @classmethod
    def get_overview(cls) -> dict:
        active_statuses = [
            CompanySubscriptionStatusChoices.ACTIVE,
            CompanySubscriptionStatusChoices.TRIALING,
            CompanySubscriptionStatusChoices.GRACE,
            CompanySubscriptionStatusChoices.PAST_DUE,
        ]
        active_subscriptions = (
            CompanySubscription.objects.filter(status__in=active_statuses)
            .select_related("subscription_price")
            .iterator()
        )

        mrr = Decimal("0")
        active_count = 0
        trialing_count = 0
        past_due_count = 0

        for company_subscription in active_subscriptions:
            subscription_price = company_subscription.subscription_price
            if company_subscription.status == CompanySubscriptionStatusChoices.TRIALING:
                trialing_count += 1
            elif company_subscription.status == CompanySubscriptionStatusChoices.PAST_DUE:
                past_due_count += 1
            else:
                active_count += 1
                mrr += cls._normalize_to_mrr(
                    Decimal(subscription_price.price or 0),
                    subscription_price.billing_frequency,
                )

        period_start = now() - timedelta(days=30)
        canceled_count = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.CANCELED,
            canceled_at__gte=period_start,
        ).count()
        expired_count = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.EXPIRED,
            updated_at__gte=period_start,
        ).count()

        trials_started = CompanySubscription.objects.filter(
            trial_start__gte=period_start,
        ).count()
        trials_converted = CompanySubscription.objects.filter(
            trial_start__isnull=False,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            updated_at__gte=period_start,
        ).count()

        overage_revenue = (
            SubscriptionInvoiceLine.objects.filter(
                line_type=SubscriptionInvoiceLineTypeChoices.OVERAGE,
                invoice__status=SubscriptionInvoiceStatusChoices.PAID,
                invoice__created_at__gte=period_start,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        status_breakdown = (
            CompanySubscription.objects.values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        )

        churn_base = max(active_count + canceled_count + expired_count, 1)
        churn_rate = Decimal(canceled_count + expired_count) / Decimal(churn_base)

        trial_conversion_rate = (
            Decimal(trials_converted) / Decimal(max(trials_started, 1))
        )

        return {
            "mrr": str(mrr.quantize(Decimal("0.01"))),
            "arr": str((mrr * Decimal("12")).quantize(Decimal("0.01"))),
            "active_subscriptions": active_count,
            "trialing_subscriptions": trialing_count,
            "past_due_subscriptions": past_due_count,
            "canceled_last_30_days": canceled_count,
            "expired_last_30_days": expired_count,
            "churn_rate_30d": str(churn_rate.quantize(Decimal("0.0001"))),
            "trials_started_30d": trials_started,
            "trials_converted_30d": trials_converted,
            "trial_conversion_rate_30d": str(
                trial_conversion_rate.quantize(Decimal("0.0001"))
            ),
            "overage_revenue_30d": str(overage_revenue.quantize(Decimal("0.01"))),
            "status_breakdown": list(status_breakdown),
        }

    @classmethod
    def get_mrr_breakdown(cls) -> list[dict]:
        active_statuses = [
            CompanySubscriptionStatusChoices.ACTIVE,
            CompanySubscriptionStatusChoices.GRACE,
        ]
        subscriptions = CompanySubscription.objects.filter(
            status__in=active_statuses
        ).select_related("subscription_price__subscription", "company")

        breakdown: dict[str, dict] = {}
        for company_subscription in subscriptions:
            subscription_price = company_subscription.subscription_price
            plan_title = subscription_price.subscription.title
            bucket = breakdown.setdefault(
                plan_title,
                {
                    "plan_title": plan_title,
                    "billing_frequency": subscription_price.billing_frequency,
                    "subscriber_count": 0,
                    "mrr": Decimal("0"),
                },
            )
            bucket["subscriber_count"] += 1
            bucket["mrr"] += cls._normalize_to_mrr(
                Decimal(subscription_price.price or 0),
                subscription_price.billing_frequency,
            )

        return [
            {
                "plan_title": item["plan_title"],
                "billing_frequency": item["billing_frequency"],
                "subscriber_count": item["subscriber_count"],
                "mrr": str(item["mrr"].quantize(Decimal("0.01"))),
            }
            for item in breakdown.values()
        ]

    @classmethod
    def get_revenue_trend(cls, *, months: int = 12) -> dict:
        months = min(max(months, 1), 24)
        period_start = now() - timedelta(days=months * 31)
        paid_lines = (
            SubscriptionInvoiceLine.objects.filter(
                invoice__status=SubscriptionInvoiceStatusChoices.PAID,
                invoice__updated_at__gte=period_start,
            )
            .annotate(month=TruncMonth("invoice__updated_at"))
            .values("month")
            .annotate(revenue=Sum("amount"))
            .order_by("month")
        )

        points = []
        mrr_points = []
        for row in paid_lines:
            if not row["month"]:
                continue
            revenue = row["revenue"] or Decimal("0")
            points.append(
                {
                    "month": row["month"].strftime("%Y-%m"),
                    "revenue": str(revenue.quantize(Decimal("0.01"))),
                }
            )
            mrr_points.append(
                {
                    "month": row["month"].strftime("%Y-%m"),
                    "mrr": str(revenue.quantize(Decimal("0.01"))),
                }
            )

        return {
            "months": months,
            "revenue": points,
            "mrr": mrr_points,
        }

    @classmethod
    def get_plan_distribution(cls) -> dict:
        active_statuses = [
            CompanySubscriptionStatusChoices.ACTIVE,
            CompanySubscriptionStatusChoices.TRIALING,
            CompanySubscriptionStatusChoices.GRACE,
            CompanySubscriptionStatusChoices.PAST_DUE,
        ]
        rows = (
            CompanySubscription.objects.filter(status__in=active_statuses)
            .values("subscription_price__subscription__title")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        total = sum(row["count"] for row in rows) or 1
        plans = []
        for row in rows:
            count = row["count"]
            plans.append(
                {
                    "plan_title": row["subscription_price__subscription__title"],
                    "subscriber_count": count,
                    "share": str(
                        (Decimal(count) / Decimal(total)).quantize(Decimal("0.0001"))
                    ),
                }
            )
        return {"total": total, "plans": plans}

    @classmethod
    def get_trial_funnel(cls, *, days: int = 90) -> dict:
        days = min(max(days, 7), 365)
        period_start = now() - timedelta(days=days)

        started = CompanySubscription.objects.filter(
            trial_start__gte=period_start,
        ).count()
        active = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.TRIALING,
            trial_end__gte=now(),
        ).count()
        converted = CompanySubscription.objects.filter(
            trial_start__isnull=False,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            updated_at__gte=period_start,
        ).count()
        expired = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.EXPIRED,
            trial_start__isnull=False,
            updated_at__gte=period_start,
        ).count()

        def rate(numerator: int, denominator: int) -> str:
            return str(
                (Decimal(numerator) / Decimal(max(denominator, 1))).quantize(
                    Decimal("0.0001")
                )
            )

        return {
            "period_days": days,
            "started": started,
            "active": active,
            "converted": converted,
            "expired": expired,
            "conversion_rate": rate(converted, started),
            "stages": [
                {"stage": "started", "count": started, "rate": "1.0000"},
                {"stage": "active", "count": active, "rate": rate(active, started)},
                {
                    "stage": "converted",
                    "count": converted,
                    "rate": rate(converted, started),
                },
                {"stage": "expired", "count": expired, "rate": rate(expired, started)},
            ],
        }
