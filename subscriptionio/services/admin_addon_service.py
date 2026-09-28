from typing import Any

from django.db import transaction
from django.db.models import Q

from subscriptionio.choices import AddOnStatusChoices
from subscriptionio.models import Subscription, SubscriptionAddOn


class AdminAddOnService:
    @classmethod
    def _linked_plans(cls, add_on: SubscriptionAddOn) -> dict[str, Any]:
        linked = add_on.applies_to_subscriptions.all()
        if not linked.exists():
            total_plans = Subscription.objects.count()
            return {
                "count": total_plans,
                "applies_to_all": True,
                "plans": [],
            }
        plans = [
            {"uid": str(plan.uid), "title": plan.title, "slug": plan.slug}
            for plan in linked
        ]
        return {
            "count": len(plans),
            "applies_to_all": False,
            "plans": plans,
        }

    @classmethod
    def _serialize_addon(cls, add_on: SubscriptionAddOn) -> dict[str, Any]:
        linked = cls._linked_plans(add_on)
        return {
            "uid": str(add_on.uid),
            "code": add_on.code,
            "title": add_on.title,
            "description": add_on.description,
            "pricing_model": add_on.pricing_model,
            "price": str(add_on.price),
            "billing_frequency": add_on.billing_frequency,
            "currency": add_on.currency,
            "status": add_on.status,
            "metric_code": add_on.metric_code,
            "unit_label": add_on.unit_label,
            "stripe_price_id": add_on.stripe_price_id,
            "linked_plans": linked,
            "created_at": add_on.created_at,
            "updated_at": add_on.updated_at,
        }

    @classmethod
    def get_addons_queryset(cls, *, status: str | None = None, search: str | None = None):
        queryset = SubscriptionAddOn.objects.prefetch_related(
            "applies_to_subscriptions"
        ).order_by("title")
        if status:
            queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search) | Q(title__icontains=search)
            )
        return queryset

    @classmethod
    def serialize_addons(cls, add_ons) -> list[dict]:
        return [cls._serialize_addon(item) for item in add_ons]

    @classmethod
    def list_addons(cls, *, status: str | None = None, search: str | None = None) -> list[dict]:
        return cls.serialize_addons(cls.get_addons_queryset(status=status, search=search))

    @classmethod
    def get_addon(cls, add_on: SubscriptionAddOn) -> dict[str, Any]:
        return cls._serialize_addon(add_on)

    @classmethod
    def _set_linked_plans(cls, add_on: SubscriptionAddOn, subscription_uids: list | None):
        if subscription_uids is None:
            return
        subscriptions = Subscription.objects.filter(uid__in=subscription_uids)
        add_on.applies_to_subscriptions.set(subscriptions)

    @classmethod
    @transaction.atomic
    def create_addon(cls, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_uids = payload.pop("applies_to_subscription_uids", None)
        code = (payload.get("code") or "").strip().upper()
        if not code:
            raise ValueError("code is required.")
        if SubscriptionAddOn.objects.filter(code__iexact=code).exists():
            raise ValueError("An add-on with this code already exists.")

        add_on = SubscriptionAddOn.objects.create(
            code=code,
            title=payload.get("title", code),
            description=payload.get("description", ""),
            pricing_model=payload.get("pricing_model"),
            price=payload.get("price", 0),
            billing_frequency=payload.get("billing_frequency"),
            currency=payload.get("currency"),
            status=payload.get("status", AddOnStatusChoices.DRAFT),
            metric_code=payload.get("metric_code"),
            unit_label=payload.get("unit_label", ""),
            stripe_price_id=payload.get("stripe_price_id"),
        )
        cls._set_linked_plans(add_on, subscription_uids)
        return cls.get_addon(add_on)

    @classmethod
    @transaction.atomic
    def update_addon(cls, add_on: SubscriptionAddOn, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_uids = payload.pop("applies_to_subscription_uids", None)
        field_map = {
            "title": "title",
            "description": "description",
            "pricing_model": "pricing_model",
            "price": "price",
            "billing_frequency": "billing_frequency",
            "currency": "currency",
            "status": "status",
            "metric_code": "metric_code",
            "unit_label": "unit_label",
            "stripe_price_id": "stripe_price_id",
        }
        update_fields = ["updated_at"]
        for key, field in field_map.items():
            if key not in payload:
                continue
            setattr(add_on, field, payload[key])
            update_fields.append(field)

        if "code" in payload:
            code = (payload["code"] or "").strip().upper()
            if (
                code
                and code != add_on.code
                and SubscriptionAddOn.objects.filter(code__iexact=code).exists()
            ):
                raise ValueError("An add-on with this code already exists.")
            add_on.code = code
            update_fields.append("code")

        add_on.save(update_fields=update_fields)
        cls._set_linked_plans(add_on, subscription_uids)
        return cls.get_addon(add_on)

    @classmethod
    @transaction.atomic
    def delete_addon(cls, add_on: SubscriptionAddOn) -> dict[str, str]:
        add_on.status = AddOnStatusChoices.DISABLED
        add_on.save(update_fields=["status", "updated_at"])
        return {"status": "disabled", "message": "Add-on disabled."}
