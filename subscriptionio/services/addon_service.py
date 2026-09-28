import json
import logging
import os
from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction

from subscriptionio.choices import (
    AddOnPricingModelChoices,
    AddOnStatusChoices,
    CompanyAddOnStatusChoices,
    CompanySubscriptionStatusChoices,
    PlanAddOnAvailabilityChoices,
    PlanVersionStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import (
    CompanyAddOn,
    PlanAddOn,
    PlanVersion,
    SubscriptionAddOn,
)
from subscriptionio.services.billing_preview_service import BillingLineItem
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.subscription_event_service import SubscriptionEventService

logger = logging.getLogger("subscriptionio.addon")
stripe.api_key = settings.STRIPE_SECRET_KEY


class AddOnService:
    @classmethod
    def _get_plan_version(cls, company) -> PlanVersion | None:
        company_subscription = EntitlementService.get_company_subscription(company)
        if company_subscription and company_subscription.plan_version_id:
            return company_subscription.plan_version
        if not company_subscription:
            return None
        return (
            PlanVersion.objects.filter(
                subscription=company_subscription.subscription_price.subscription,
                status=PlanVersionStatusChoices.PUBLISHED,
            )
            .order_by("-version_no")
            .first()
        )

    @classmethod
    def _addon_is_available(
        cls,
        add_on: SubscriptionAddOn,
        *,
        subscription,
        plan_version: PlanVersion | None,
    ) -> bool:
        if add_on.status != AddOnStatusChoices.ACTIVE:
            return False

        linked_plans = add_on.applies_to_subscriptions.all()
        if linked_plans.exists() and not linked_plans.filter(id=subscription.id).exists():
            return False

        if plan_version:
            plan_link = PlanAddOn.objects.filter(
                plan_version=plan_version,
                add_on=add_on,
            ).first()
            if plan_link and plan_link.availability == PlanAddOnAvailabilityChoices.UNAVAILABLE:
                return False

        return True

    @classmethod
    def _serialize_addon(cls, add_on: SubscriptionAddOn, *, availability: str | None = None) -> dict[str, Any]:
        return {
            "uid": str(add_on.uid),
            "code": add_on.code,
            "title": add_on.title,
            "description": add_on.description,
            "pricing_model": add_on.pricing_model,
            "price": str(add_on.price),
            "billing_frequency": add_on.billing_frequency,
            "currency": add_on.currency,
            "metric_code": add_on.metric_code,
            "unit_label": add_on.unit_label,
            "availability": availability or PlanAddOnAvailabilityChoices.OPTIONAL,
        }

    @classmethod
    def _serialize_company_addon(cls, company_addon: CompanyAddOn) -> dict[str, Any]:
        add_on = company_addon.add_on
        return {
            "uid": str(company_addon.uid),
            "add_on_uid": str(add_on.uid),
            "code": add_on.code,
            "title": add_on.title,
            "status": company_addon.status,
            "quantity": company_addon.quantity,
            "unit_price": str(company_addon.unit_price),
            "pricing_model": add_on.pricing_model,
            "billing_frequency": add_on.billing_frequency,
            "currency": add_on.currency,
        }

    @classmethod
    def list_for_company(cls, company) -> dict[str, Any]:
        company_subscription = EntitlementService.get_company_subscription(company)
        subscription = None
        plan_version = cls._get_plan_version(company)
        if company_subscription:
            subscription = company_subscription.subscription_price.subscription

        available: list[dict] = []
        if subscription:
            for add_on in SubscriptionAddOn.objects.filter(
                status=AddOnStatusChoices.ACTIVE
            ).prefetch_related("applies_to_subscriptions"):
                if not cls._addon_is_available(
                    add_on,
                    subscription=subscription,
                    plan_version=plan_version,
                ):
                    continue
                availability = PlanAddOnAvailabilityChoices.OPTIONAL
                if plan_version:
                    plan_link = PlanAddOn.objects.filter(
                        plan_version=plan_version,
                        add_on=add_on,
                    ).first()
                    if plan_link:
                        availability = plan_link.availability
                available.append(cls._serialize_addon(add_on, availability=availability))

        active = [
            cls._serialize_company_addon(item)
            for item in CompanyAddOn.objects.filter(
                company=company,
                status=CompanyAddOnStatusChoices.ACTIVE,
            ).select_related("add_on")
        ]

        return {"available": available, "active": active}

    @classmethod
    def resolve_addons(
        cls,
        company,
        *,
        addon_uids: list | None = None,
        addon_codes: list | None = None,
        quantities: dict[str, int] | None = None,
        target_subscription=None,
        target_plan_version: PlanVersion | None = None,
    ) -> list[tuple[SubscriptionAddOn, int]]:
        if not addon_uids and not addon_codes:
            return []

        company_subscription = EntitlementService.get_company_subscription(company)
        subscription = target_subscription
        plan_version = target_plan_version or cls._get_plan_version(company)
        if not subscription and company_subscription:
            subscription = company_subscription.subscription_price.subscription

        queryset = SubscriptionAddOn.objects.filter(status=AddOnStatusChoices.ACTIVE)
        if addon_uids:
            addons = list(queryset.filter(uid__in=addon_uids))
        else:
            normalized = [(code or "").strip().upper() for code in addon_codes or []]
            addons = list(queryset.filter(code__in=normalized))

        quantities = quantities or {}
        resolved: list[tuple[SubscriptionAddOn, int]] = []
        for add_on in addons:
            if (
                subscription
                and not cls._addon_is_available(
                    add_on,
                    subscription=subscription,
                    plan_version=plan_version,
                )
            ):
                raise ValueError(f"Add-on {add_on.code} is not available for your plan.")
            qty = int(quantities.get(str(add_on.uid), quantities.get(add_on.code, 1)))
            if qty < 1:
                raise ValueError(f"Invalid quantity for add-on {add_on.code}.")
            resolved.append((add_on, qty))
        return resolved

    @classmethod
    def build_preview_lines(
        cls, resolved: list[tuple[SubscriptionAddOn, int]]
    ) -> tuple[list[BillingLineItem], Decimal]:
        lines: list[BillingLineItem] = []
        total = Decimal("0")
        for add_on, quantity in resolved:
            unit_amount = Decimal(add_on.price or 0)
            amount = unit_amount * Decimal(quantity)
            total += amount
            lines.append(
                BillingLineItem(
                    line_type="ADDON",
                    description=f"Add-on: {add_on.title}",
                    quantity=Decimal(quantity),
                    unit_amount=unit_amount,
                    amount=amount,
                    metadata={
                        "addon_uid": str(add_on.uid),
                        "addon_code": add_on.code,
                        "pricing_model": add_on.pricing_model,
                    },
                )
            )
        return lines, total

    @classmethod
    def encode_addon_payload(cls, resolved: list[tuple[SubscriptionAddOn, int]]) -> str:
        return json.dumps(
            [
                {"uid": str(add_on.uid), "quantity": quantity}
                for add_on, quantity in resolved
            ]
        )

    @classmethod
    def decode_addon_payload(cls, payload: str | None) -> list[dict]:
        if not payload:
            return []
        try:
            data = json.loads(payload)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @classmethod
    @transaction.atomic
    def attach_from_checkout(
        cls,
        *,
        company,
        company_subscription,
        addon_payload: str | None,
        stripe_items: dict[str, str] | None = None,
    ) -> list[CompanyAddOn]:
        items = cls.decode_addon_payload(addon_payload)
        if not items:
            return []

        stripe_items = stripe_items or {}
        created: list[CompanyAddOn] = []
        for item in items:
            add_on = SubscriptionAddOn.objects.filter(uid=item.get("uid")).first()
            if not add_on:
                continue
            quantity = int(item.get("quantity", 1))
            existing = CompanyAddOn.objects.filter(
                company=company,
                add_on=add_on,
                status=CompanyAddOnStatusChoices.ACTIVE,
            ).first()
            if existing:
                existing.quantity = quantity
                existing.unit_price = add_on.price
                existing.company_subscription = company_subscription
                existing.stripe_subscription_item_id = stripe_items.get(str(add_on.uid))
                existing.save(
                    update_fields=[
                        "quantity",
                        "unit_price",
                        "company_subscription",
                        "stripe_subscription_item_id",
                        "updated_at",
                    ]
                )
                created.append(existing)
                continue

            created.append(
                CompanyAddOn.objects.create(
                    company=company,
                    company_subscription=company_subscription,
                    add_on=add_on,
                    quantity=quantity,
                    unit_price=add_on.price,
                    stripe_subscription_item_id=stripe_items.get(str(add_on.uid)),
                )
            )

        if created:
            SubscriptionEventService.record(
                company=company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
                source=SubscriptionEventSourceChoices.WEBHOOK,
                payload={
                    "action": "addons_attached",
                    "addons": [item.add_on.code for item in created],
                },
            )
        return created

    @classmethod
    @transaction.atomic
    def purchase_for_active_subscription(
        cls,
        *,
        company,
        user,
        addon_uid: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            raise ValueError("An active subscription is required to purchase add-ons.")
        if company_subscription.status not in {
            CompanySubscriptionStatusChoices.ACTIVE,
            CompanySubscriptionStatusChoices.TRIALING,
            CompanySubscriptionStatusChoices.GRACE,
        }:
            raise ValueError("Your subscription must be active to purchase add-ons.")

        resolved = cls.resolve_addons(
            company,
            addon_uids=[addon_uid],
            quantities={addon_uid: quantity},
        )
        if not resolved:
            raise ValueError("Add-on not found.")
        add_on, qty = resolved[0]

        if CompanyAddOn.objects.filter(
            company=company,
            add_on=add_on,
            status=CompanyAddOnStatusChoices.ACTIVE,
        ).exists():
            raise ValueError(f"Add-on {add_on.code} is already active.")

        stripe_subscription_id = company_subscription.stripe_subscription_id
        if not stripe_subscription_id:
            raise ValueError("Stripe subscription is not configured for this company.")

        stripe_item_id = None
        if add_on.pricing_model == AddOnPricingModelChoices.ONE_TIME:
            checkout_session = stripe.checkout.Session.create(
                customer=company_subscription.stripe_customer_id,
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": add_on.currency.lower(),
                            "unit_amount": int(Decimal(add_on.price) * 100),
                            "product_data": {"name": add_on.title},
                        },
                        "quantity": qty,
                    }
                ],
                success_url=(
                    f"{os.getenv('BASE_LANDING_FRONTEND_URL')}/payment-success"
                    "?success=true&session_id={CHECKOUT_SESSION_ID}"
                ),
                cancel_url=(
                    f"{os.getenv('BASE_LANDING_FRONTEND_URL')}/payment-success?success=false"
                ),
                metadata={
                    "checkout_version": "v2_addon",
                    "company_id": str(company.uid),
                    "addon_payload": cls.encode_addon_payload([(add_on, qty)]),
                },
            )
            return {
                "checkout_url": checkout_session.url,
                "session_id": checkout_session.id,
                "mode": "payment",
            }

        if add_on.stripe_price_id:
            stripe_item = stripe.SubscriptionItem.create(
                subscription=stripe_subscription_id,
                price=add_on.stripe_price_id,
                quantity=qty,
            )
            stripe_item_id = stripe_item.id
        else:
            from subscriptionio.services.stripe_checkout_service import StripeCheckoutService

            billing_frequency = (
                add_on.billing_frequency
                or company_subscription.subscription_price.billing_frequency
            )
            interval, interval_count = StripeCheckoutService._stripe_recurring_interval(
                billing_frequency
            )
            recurring = {"interval": interval}
            if interval_count > 1:
                recurring["interval_count"] = interval_count
            stripe_item = stripe.SubscriptionItem.create(
                subscription=stripe_subscription_id,
                price_data={
                    "currency": add_on.currency.lower(),
                    "unit_amount": int(Decimal(add_on.price) * 100),
                    "recurring": recurring,
                    "product_data": {"name": add_on.title},
                },
                quantity=qty,
            )
            stripe_item_id = stripe_item.id

        company_addon = CompanyAddOn.objects.create(
            company=company,
            company_subscription=company_subscription,
            add_on=add_on,
            quantity=qty,
            unit_price=add_on.price,
            stripe_subscription_item_id=stripe_item_id,
        )
        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
            source=SubscriptionEventSourceChoices.API,
            actor=getattr(user, "get_employee", lambda: None)(),
            payload={
                "action": "addon_purchased",
                "addon_code": add_on.code,
                "quantity": qty,
            },
        )
        return {
            "company_addon": cls._serialize_company_addon(company_addon),
            "mode": "subscription_item",
        }
