from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction
from django.utils.timezone import now

from subscriptionio.choices import OfferStatusChoices, SubscriptionEventSourceChoices, SubscriptionEventTypeChoices
from subscriptionio.models import SubscriptionOffer
from subscriptionio.services.coupon_service import CouponService
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.lifecycle_service import LifecycleService
from subscriptionio.services.subscription_event_service import SubscriptionEventService

stripe.api_key = settings.STRIPE_SECRET_KEY


@dataclass
class OfferValidationResult:
    valid: bool
    offer: SubscriptionOffer | None = None
    coupon_code: str | None = None
    message: str = ""
    discount_amount: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)


class OfferService:
    INVALID_MESSAGE = "This offer is not valid."
    NO_COUPON_MESSAGE = "This offer is not configured with a discount."
    RETENTION_ONLY_MESSAGE = "This offer is only available as a retention offer."
    NOT_ELIGIBLE_MESSAGE = "You are not eligible for this offer."

    @classmethod
    def _normalize_code(cls, code: str) -> str:
        return (code or "").strip().upper()

    @classmethod
    def _offer_is_active(cls, offer: SubscriptionOffer) -> bool:
        if offer.status != OfferStatusChoices.ACTIVE:
            return False
        current = now()
        if offer.valid_from and current < offer.valid_from:
            return False
        if offer.valid_until and current > offer.valid_until:
            return False
        return True

    @classmethod
    def _resolve_subscription_price(cls, company, subscription_price=None):
        if subscription_price:
            return subscription_price
        company_subscription = EntitlementService.get_company_subscription(company)
        if company_subscription:
            return company_subscription.subscription_price
        return None

    @classmethod
    def _serialize_offer(
        cls,
        offer: SubscriptionOffer,
        *,
        validation: OfferValidationResult | None = None,
    ) -> dict[str, Any]:
        payload = {
            "uid": str(offer.uid),
            "code": offer.code,
            "title": offer.title,
            "description": offer.description,
            "is_retention_offer": offer.is_retention_offer,
            "valid_from": offer.valid_from,
            "valid_until": offer.valid_until,
            "coupon_code": offer.coupon.code if offer.coupon else None,
        }
        if validation and validation.valid:
            payload["discount_amount"] = str(validation.discount_amount)
            payload["metadata"] = validation.metadata
        return payload

    @classmethod
    def validate(
        cls,
        offer_code: str,
        *,
        company,
        subscription_price=None,
        retention_context: bool = False,
    ) -> OfferValidationResult:
        code = cls._normalize_code(offer_code)
        if not code:
            return OfferValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        offer = (
            SubscriptionOffer.objects.filter(code__iexact=code)
            .select_related("coupon")
            .prefetch_related("coupon__applies_to_subscriptions")
            .first()
        )
        if not offer or not cls._offer_is_active(offer):
            return OfferValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        if offer.is_retention_offer and not retention_context:
            return OfferValidationResult(
                valid=False,
                offer=offer,
                message=cls.RETENTION_ONLY_MESSAGE,
            )

        if retention_context and not offer.is_retention_offer:
            return OfferValidationResult(
                valid=False,
                offer=offer,
                message=cls.NOT_ELIGIBLE_MESSAGE,
            )

        if retention_context:
            company_subscription = EntitlementService.get_company_subscription(company)
            if not company_subscription or company_subscription.status not in LifecycleService.CANCELABLE_STATUSES:
                return OfferValidationResult(
                    valid=False,
                    offer=offer,
                    message=cls.NOT_ELIGIBLE_MESSAGE,
                )

        if not offer.coupon:
            return OfferValidationResult(
                valid=False,
                offer=offer,
                message=cls.NO_COUPON_MESSAGE,
            )

        subscription_price = cls._resolve_subscription_price(company, subscription_price)
        existing_discount = Decimal("0")
        if subscription_price:
            from subscriptionio.services.billing_preview_service import BillingPreviewService

            existing_discount = BillingPreviewService._apply_price_discount(subscription_price)[1]

        coupon_result = CouponService.validate(
            offer.coupon.code,
            company=company,
            subscription_price=subscription_price,
            existing_plan_discount=existing_discount,
        )
        if not coupon_result.valid:
            return OfferValidationResult(
                valid=False,
                offer=offer,
                message=coupon_result.message,
            )

        return OfferValidationResult(
            valid=True,
            offer=offer,
            coupon_code=offer.coupon.code,
            discount_amount=coupon_result.discount_amount,
            metadata={
                "offer_code": offer.code,
                "offer_title": offer.title,
                "coupon_code": offer.coupon.code,
                "is_retention_offer": offer.is_retention_offer,
                **coupon_result.metadata,
            },
        )

    @classmethod
    def list_offers(
        cls,
        company,
        *,
        subscription_price=None,
        retention_only: bool = False,
    ) -> list[dict[str, Any]]:
        queryset = SubscriptionOffer.objects.filter(
            is_retention_offer=retention_only,
            status=OfferStatusChoices.ACTIVE,
        ).select_related("coupon")

        results: list[dict[str, Any]] = []
        for offer in queryset.order_by("-created_at"):
            if not cls._offer_is_active(offer):
                continue
            validation = cls.validate(
                offer.code,
                company=company,
                subscription_price=subscription_price,
                retention_context=retention_only,
            )
            if validation.valid:
                results.append(cls._serialize_offer(offer, validation=validation))
        return results

    @classmethod
    def get_retention_offers(cls, company) -> list[dict[str, Any]]:
        return cls.list_offers(company, retention_only=True)

    @classmethod
    def resolve_coupon_code(
        cls,
        *,
        offer_code: str | None,
        coupon_code: str | None,
        company,
        subscription_price=None,
    ) -> tuple[str | None, OfferValidationResult | None]:
        if not offer_code:
            return coupon_code, None

        validation = cls.validate(
            offer_code,
            company=company,
            subscription_price=subscription_price,
            retention_context=False,
        )
        if not validation.valid:
            raise ValueError(validation.message)
        if coupon_code and coupon_code.upper() != validation.coupon_code.upper():
            raise ValueError("offer_code and coupon_code cannot be combined.")
        return validation.coupon_code, validation

    @classmethod
    @transaction.atomic
    def accept_retention_offer(
        cls,
        company,
        offer_code: str,
        *,
        actor=None,
    ) -> dict[str, Any]:
        validation = cls.validate(
            offer_code,
            company=company,
            retention_context=True,
        )
        if not validation.valid or not validation.offer:
            raise ValueError(validation.message)

        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            raise ValueError("No subscription found.")

        previous_status = company_subscription.status
        stripe_subscription_id = company_subscription.stripe_subscription_id
        if stripe_subscription_id:
            try:
                stripe.Subscription.modify(
                    stripe_subscription_id,
                    cancel_at_period_end=False,
                )
            except stripe.error.StripeError as exc:
                message = getattr(exc, "user_message", str(exc))
                raise ValueError(f"Unable to apply retention offer: {message}") from exc

        from subscriptionio.choices import CompanySubscriptionStatusChoices

        company_subscription.cancel_at_period_end = False
        company_subscription.canceled_at = None
        if company_subscription.status == CompanySubscriptionStatusChoices.CANCELED:
            company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        company_subscription.applied_coupon = validation.offer.coupon
        company_subscription.save(
            update_fields=[
                "cancel_at_period_end",
                "canceled_at",
                "status",
                "applied_coupon",
                "updated_at",
            ]
        )
        EntitlementService.invalidate(company.id)
        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.RETENTION_OFFER_ACCEPTED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=SubscriptionEventSourceChoices.API,
            actor=actor,
            payload={
                "offer_code": validation.offer.code,
                "coupon_code": validation.coupon_code,
            },
        )
        return cls._serialize_offer(validation.offer, validation=validation)
