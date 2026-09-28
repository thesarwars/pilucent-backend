from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Count

from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    PlanAddOnAvailabilityChoices,
    PlanVersionStatusChoices,
    SubscriptionKindChoices,
    SubscriptionStatusChoices,
)
from subscriptionio.models import (
    CompanySubscription,
    PlanAddOn,
    PlanVersion,
    Subscription,
    SubscriptionAddOn,
    SubscriptionPrice,
)
from subscriptionio.services.analytics_service import SubscriptionAnalyticsService
from subscriptionio.services.plan_version_service import PlanVersionService


class AdminPlanCatalogService:
    ACTIVE_STATUSES = {
        CompanySubscriptionStatusChoices.ACTIVE,
        CompanySubscriptionStatusChoices.TRIALING,
        CompanySubscriptionStatusChoices.GRACE,
        CompanySubscriptionStatusChoices.PAST_DUE,
    }

    @classmethod
    def _subscriber_counts(cls) -> dict[int, int]:
        counts: dict[int, int] = {}
        for row in (
            CompanySubscription.objects.filter(
                kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
                status__in=cls.ACTIVE_STATUSES,
            )
            .values("subscription_price__subscription_id")
            .annotate(count=Count("id"))
        ):
            sub_id = row["subscription_price__subscription_id"]
            if sub_id:
                counts[sub_id] = row["count"]
        return counts

    @classmethod
    def _serialize_prices(cls, subscription: Subscription) -> list[dict[str, Any]]:
        return [
            {
                "uid": str(price.uid),
                "billing_frequency": price.billing_frequency,
                "price": str(price.price),
                "currency": price.currency,
                "discount": str(price.discount or 0),
                "discount_kind": price.discount_kind,
                "is_active": price.is_active,
            }
            for price in SubscriptionPrice.objects.filter(subscription=subscription)
            .order_by("billing_frequency", "currency")
        ]

    @classmethod
    def _serialize_plan(
        cls,
        subscription: Subscription,
        *,
        subscriber_counts: dict[int, int] | None = None,
    ) -> dict[str, Any]:
        subscriber_counts = subscriber_counts or cls._subscriber_counts()
        published_version = (
            PlanVersion.objects.filter(
                subscription=subscription,
                status=PlanVersionStatusChoices.PUBLISHED,
            )
            .order_by("-version_no")
            .first()
        )
        draft_version = (
            PlanVersion.objects.filter(
                subscription=subscription,
                status=PlanVersionStatusChoices.DRAFT,
            )
            .order_by("-version_no")
            .first()
        )
        prices = cls._serialize_prices(subscription)
        monthly_price = next(
            (
                p
                for p in prices
                if p["billing_frequency"] == "MONTHLY"
                and p["currency"] == subscription.currency
                and p["is_active"]
            ),
            next((p for p in prices if p["is_active"]), None),
        )

        return {
            "uid": str(subscription.uid),
            "slug": subscription.slug,
            "title": subscription.title,
            "status": subscription.status,
            "kind": subscription.kind,
            "description": subscription.description,
            "currency": subscription.currency,
            "employee_limit": subscription.employee_limit,
            "user_limit": subscription.user_limit,
            "storage_limit": subscription.storage_limit,
            "trial_period": subscription.trial_period,
            "note": subscription.note,
            "subscriber_count": subscriber_counts.get(subscription.id, 0),
            "published_version": (
                {
                    "uid": str(published_version.uid),
                    "version_no": published_version.version_no,
                    "status": published_version.status,
                }
                if published_version
                else None
            ),
            "draft_version": (
                {
                    "uid": str(draft_version.uid),
                    "version_no": draft_version.version_no,
                    "status": draft_version.status,
                }
                if draft_version
                else None
            ),
            "monthly_price": monthly_price,
            "prices": prices,
            "mrr": (
                str(
                    SubscriptionAnalyticsService._normalize_to_mrr(
                        Decimal(monthly_price["price"]),
                        monthly_price["billing_frequency"],
                    ).quantize(Decimal("0.01"))
                )
                if monthly_price
                else "0"
            ),
        }

    @classmethod
    def get_plans_queryset(cls):
        return Subscription.objects.all().order_by("title")

    @classmethod
    def serialize_plans(cls, subscriptions) -> list[dict[str, Any]]:
        subscriber_counts = cls._subscriber_counts()
        return [
            cls._serialize_plan(subscription, subscriber_counts=subscriber_counts)
            for subscription in subscriptions
        ]

    @classmethod
    def list_plans(cls) -> list[dict[str, Any]]:
        return cls.serialize_plans(cls.get_plans_queryset())

    @classmethod
    def get_plan(cls, subscription: Subscription) -> dict[str, Any]:
        return cls._serialize_plan(subscription)

    @classmethod
    def _upsert_prices(cls, subscription: Subscription, prices: list[dict] | None):
        if not prices:
            return
        for item in prices:
            price_uid = item.get("uid")
            defaults = {
                "billing_frequency": item.get("billing_frequency"),
                "price": item.get("price", 0),
                "currency": item.get("currency", subscription.currency),
                "discount": item.get("discount", 0),
                "discount_kind": item.get("discount_kind"),
                "is_active": item.get("is_active", True),
            }
            if price_uid:
                price = SubscriptionPrice.objects.filter(
                    subscription=subscription,
                    uid=price_uid,
                ).first()
                if price:
                    for key, value in defaults.items():
                        if value is not None:
                            setattr(price, key, value)
                    price.save()
                continue
            SubscriptionPrice.objects.update_or_create(
                subscription=subscription,
                billing_frequency=defaults["billing_frequency"],
                currency=defaults["currency"],
                defaults=defaults,
            )

    @classmethod
    @transaction.atomic
    def create_plan(cls, payload: dict[str, Any]) -> dict[str, Any]:
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("title is required.")

        subscription = Subscription.objects.create(
            title=title,
            description=payload.get("description", ""),
            status=payload.get("status", SubscriptionStatusChoices.DRAFT),
            kind=payload.get("kind", SubscriptionKindChoices.COMPANY_SUBSCRIPTION),
            currency=payload.get("currency", "USD"),
            employee_limit=int(payload.get("employee_limit", 0)),
            user_limit=int(payload.get("user_limit", 0)),
            storage_limit=int(payload.get("storage_limit", 0)),
            trial_period=int(payload.get("trial_period", 0)),
            note=payload.get("note", ""),
        )
        cls._upsert_prices(subscription, payload.get("prices"))

        draft = PlanVersionService.create_draft_version(subscription)
        if payload.get("publish_initial_version"):
            PlanVersionService.publish(draft)

        return cls.get_plan(subscription)

    @classmethod
    @transaction.atomic
    def update_plan(cls, subscription: Subscription, payload: dict[str, Any]) -> dict[str, Any]:
        field_map = {
            "title": "title",
            "description": "description",
            "status": "status",
            "kind": "kind",
            "currency": "currency",
            "employee_limit": "employee_limit",
            "user_limit": "user_limit",
            "storage_limit": "storage_limit",
            "trial_period": "trial_period",
            "note": "note",
        }
        update_fields = ["updated_at"]
        for key, field in field_map.items():
            if key not in payload:
                continue
            setattr(subscription, field, payload[key])
            update_fields.append(field)
        subscription.save(update_fields=update_fields)
        cls._upsert_prices(subscription, payload.get("prices"))
        return cls.get_plan(subscription)

    @classmethod
    @transaction.atomic
    def archive_plan(cls, subscription: Subscription) -> dict[str, str]:
        subscription.status = SubscriptionStatusChoices.REMOVED
        subscription.save(update_fields=["status", "updated_at"])
        return {"status": "archived", "message": "Plan archived."}

    @classmethod
    def get_plan_version_addons(cls, plan_version: PlanVersion) -> list[dict[str, Any]]:
        links = PlanAddOn.objects.filter(plan_version=plan_version).select_related("add_on")
        return [
            {
                "addon_uid": str(link.add_on.uid),
                "code": link.add_on.code,
                "title": link.add_on.title,
                "availability": link.availability,
            }
            for link in links
        ]

    @classmethod
    @transaction.atomic
    def sync_plan_version_addons(
        cls,
        plan_version: PlanVersion,
        addons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if plan_version.status != PlanVersionStatusChoices.DRAFT:
            raise ValueError("Add-on links can only be edited on draft plan versions.")

        PlanAddOn.objects.filter(plan_version=plan_version).delete()
        for item in addons:
            addon_uid = item.get("addon_uid")
            if not addon_uid:
                continue
            add_on = SubscriptionAddOn.objects.filter(uid=addon_uid).first()
            if not add_on:
                continue
            PlanAddOn.objects.create(
                plan_version=plan_version,
                add_on=add_on,
                availability=item.get(
                    "availability", PlanAddOnAvailabilityChoices.OPTIONAL
                ),
            )
        return cls.get_plan_version_addons(plan_version)
