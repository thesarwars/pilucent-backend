import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings
from django.db import models, transaction
from django.utils.timezone import now

from common.choices import DiscountKind

from subscriptionio.choices import CouponStatusChoices
from subscriptionio.models import CouponRedemption, SubscriptionCoupon

logger = logging.getLogger("subscriptionio.coupon")
stripe.api_key = settings.STRIPE_SECRET_KEY


@dataclass
class CouponValidationResult:
    valid: bool
    coupon: SubscriptionCoupon | None = None
    message: str = ""
    discount_amount: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)


class CouponService:
    INVALID_MESSAGE = "This coupon code is not valid."
    EXPIRED_MESSAGE = "This coupon has expired."
    LIMIT_MESSAGE = "This coupon has reached its redemption limit."
    STACKING_MESSAGE = "This coupon cannot be combined with the current plan discount."

    @classmethod
    def _normalize_code(cls, coupon_code: str) -> str:
        return (coupon_code or "").strip().upper()

    @classmethod
    def _coupon_is_active(cls, coupon: SubscriptionCoupon) -> bool:
        if coupon.status != CouponStatusChoices.ACTIVE:
            return False
        current = now()
        if coupon.valid_from and current < coupon.valid_from:
            return False
        if coupon.valid_until and current > coupon.valid_until:
            return False
        if (
            coupon.max_redemptions is not None
            and coupon.redemption_count >= coupon.max_redemptions
        ):
            return False
        return True

    @classmethod
    def _applies_to_subscription(cls, coupon: SubscriptionCoupon, subscription) -> bool:
        if not coupon.applies_to_subscriptions.exists():
            return True
        return coupon.applies_to_subscriptions.filter(id=subscription.id).exists()

    @classmethod
    def _company_redemption_count(cls, coupon: SubscriptionCoupon, company) -> int:
        if not company:
            return 0
        return CouponRedemption.objects.filter(coupon=coupon, company=company).count()

    @classmethod
    def calculate_discount(
        cls,
        coupon: SubscriptionCoupon,
        *,
        base_amount: Decimal,
        overage_total: Decimal = Decimal("0"),
    ) -> Decimal:
        taxable_base = max(Decimal("0"), base_amount + overage_total)
        if taxable_base <= 0:
            return Decimal("0")

        if coupon.discount_kind == DiscountKind.PERCENTAGE:
            discount_value = Decimal(coupon.discount_value)
            if discount_value < 1:
                discount_value *= Decimal("100")
            return min(taxable_base, (taxable_base * discount_value) / Decimal("100"))

        return min(taxable_base, Decimal(coupon.discount_value))

    @classmethod
    def validate(
        cls,
        coupon_code: str,
        *,
        company=None,
        subscription_price=None,
        existing_plan_discount: Decimal = Decimal("0"),
    ) -> CouponValidationResult:
        code = cls._normalize_code(coupon_code)
        if not code:
            return CouponValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        coupon = (
            SubscriptionCoupon.objects.filter(code__iexact=code)
            .prefetch_related("applies_to_subscriptions")
            .first()
        )
        if not coupon:
            return CouponValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        if not cls._coupon_is_active(coupon):
            return CouponValidationResult(
                valid=False,
                coupon=coupon,
                message=cls.EXPIRED_MESSAGE,
            )

        if subscription_price and not cls._applies_to_subscription(
            coupon, subscription_price.subscription
        ):
            return CouponValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        if company:
            if (
                cls._company_redemption_count(coupon, company)
                >= coupon.max_redemptions_per_company
            ):
                return CouponValidationResult(
                    valid=False,
                    coupon=coupon,
                    message=cls.LIMIT_MESSAGE,
                )

        if existing_plan_discount > 0 and not coupon.is_stackable:
            return CouponValidationResult(
                valid=False,
                coupon=coupon,
                message=cls.STACKING_MESSAGE,
            )

        base_amount = Decimal(subscription_price.price or 0) if subscription_price else Decimal("0")
        discount_amount = cls.calculate_discount(coupon, base_amount=base_amount)

        return CouponValidationResult(
            valid=True,
            coupon=coupon,
            discount_amount=discount_amount,
            metadata={
                "code": coupon.code,
                "discount_kind": coupon.discount_kind,
                "discount_value": str(coupon.discount_value),
                "is_stackable": coupon.is_stackable,
            },
        )

    @classmethod
    def get_or_create_stripe_coupon(cls, coupon: SubscriptionCoupon) -> str | None:
        if coupon.stripe_coupon_id:
            return coupon.stripe_coupon_id

        try:
            if coupon.discount_kind == DiscountKind.PERCENTAGE:
                discount_value = float(coupon.discount_value)
                if discount_value < 1:
                    discount_value *= 100
                stripe_coupon = stripe.Coupon.create(
                    percent_off=discount_value,
                    duration="once",
                    metadata={"coupon_code": coupon.code, "source": "subscription_coupon"},
                )
            else:
                stripe_coupon = stripe.Coupon.create(
                    id=f"SUB_COUPON_{uuid.uuid4().hex[:10].upper()}",
                    amount_off=int(Decimal(coupon.discount_value) * 100),
                    currency="usd",
                    duration="once",
                    metadata={"coupon_code": coupon.code, "source": "subscription_coupon"},
                )
            coupon.stripe_coupon_id = stripe_coupon.id
            coupon.save(update_fields=["stripe_coupon_id", "updated_at"])
            return stripe_coupon.id
        except Exception:
            logger.exception("Failed to create Stripe coupon for code=%s", coupon.code)
            return None

    @classmethod
    @transaction.atomic
    def redeem(
        cls,
        coupon: SubscriptionCoupon,
        *,
        company,
        redeemed_by=None,
        checkout_session_id: str | None = None,
        discount_amount: Decimal = Decimal("0"),
    ) -> CouponRedemption:
        redemption = CouponRedemption.objects.create(
            coupon=coupon,
            company=company,
            redeemed_by=redeemed_by,
            checkout_session_id=checkout_session_id,
            discount_amount=discount_amount,
        )
        SubscriptionCoupon.objects.filter(id=coupon.id).update(
            redemption_count=models.F("redemption_count") + 1
        )
        return redemption
