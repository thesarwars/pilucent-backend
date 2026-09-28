import logging
import os
import uuid
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction

from common.choices import DiscountKind
from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    LimitMetricChoices,
    SubscriptionPriceBillingFrequencyChoices,
)
from subscriptionio.models import CompanySubscription, PlanLimit, SubscriptionAddOn, SubscriptionPrice
from subscriptionio.models import SubscriptionProgramSettings
from subscriptionio.services.addon_service import AddOnService
from subscriptionio.services.billing_preview_service import BillingPreviewService
from subscriptionio.services.coupon_service import CouponService
from subscriptionio.services.offer_service import OfferService
from subscriptionio.services.plan_change_guard_service import PlanChangeGuardService
from subscriptionio.services.referral_service import ReferralService
from subscriptionio.services.subscription_billing_service import SubscriptionBillingService

logger = logging.getLogger("weapi.stripe")
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeCheckoutService:
    @classmethod
    def _stripe_recurring_interval(cls, billing_frequency: str) -> tuple[str, int]:
        mapping = {
            SubscriptionPriceBillingFrequencyChoices.WEEKLY: ("week", 1),
            SubscriptionPriceBillingFrequencyChoices.MONTHLY: ("month", 1),
            SubscriptionPriceBillingFrequencyChoices.QUARTERLY: ("month", 3),
            SubscriptionPriceBillingFrequencyChoices.HALF_YEARLY: ("month", 6),
            SubscriptionPriceBillingFrequencyChoices.YEARLY: ("year", 1),
        }
        return mapping.get(billing_frequency, ("month", 1))

    @classmethod
    def _create_coupon_for_discount(
        cls, discount, discount_kind=DiscountKind.FLAT, currency="USD"
    ):
        coupon_id = f"DISCOUNT_{uuid.uuid4().hex[:8].upper()}"
        try:
            if discount_kind == DiscountKind.PERCENTAGE:
                discount_value = float(discount)
                if discount_value < 1:
                    discount_value *= 100
                coupon = stripe.Coupon.create(
                    percent_off=discount_value,
                    duration="once",
                    metadata={"source": "subscription_percentage_discount"},
                )
            else:
                amount_off = int(Decimal(discount) * 100)
                coupon = stripe.Coupon.create(
                    id=coupon_id,
                    amount_off=amount_off,
                    currency=currency.lower(),
                    duration="once",
                    metadata={"source": "subscription_flat_discount"},
                )
            return coupon.id
        except Exception as exc:
            logger.error("Error creating coupon: %s", exc)
            return None

    @classmethod
    def _get_plan_limit(
        cls, plan_version, metric_code: str
    ) -> PlanLimit | None:
        if not plan_version:
            return None
        return plan_version.limits.filter(metric_code=metric_code).first()

    @classmethod
    def build_stripe_line_items(
        cls,
        *,
        preview,
        subscription_price: SubscriptionPrice,
        plan_version,
        include_overage: bool = True,
    ) -> list[dict]:
        if not subscription_price.stripe_price_id:
            raise ValueError("Subscription price is missing stripe_price_id")

        line_items = [
            {
                "price": subscription_price.stripe_price_id,
                "quantity": 1,
            }
        ]
        interval, interval_count = cls._stripe_recurring_interval(
            subscription_price.billing_frequency
        )
        currency = preview.currency.lower()

        for line in preview.lines:
            if line.line_type == "ADDON":
                metric_uid = line.metadata.get("addon_uid")
                add_on = SubscriptionAddOn.objects.filter(uid=metric_uid).first()
                quantity = int(line.quantity)
                if quantity <= 0:
                    continue
                if add_on and add_on.stripe_price_id:
                    line_items.append(
                        {"price": add_on.stripe_price_id, "quantity": quantity}
                    )
                    continue

                unit_amount_cents = int(Decimal(line.unit_amount) * 100)
                if unit_amount_cents <= 0:
                    continue
                price_data = {
                    "currency": currency,
                    "unit_amount": unit_amount_cents,
                    "product_data": {"name": line.description},
                }
                if add_on and add_on.pricing_model != "ONE_TIME":
                    recurring = {"interval": interval}
                    if interval_count > 1:
                        recurring["interval_count"] = interval_count
                    price_data["recurring"] = recurring
                line_items.append(
                    {"price_data": price_data, "quantity": quantity}
                )
                continue

            if line.line_type != "OVERAGE" or not include_overage:
                continue

            metric_code = line.metadata.get("metric_code")
            quantity = int(line.quantity)
            if quantity <= 0:
                continue

            plan_limit = cls._get_plan_limit(plan_version, metric_code)
            if plan_limit and plan_limit.stripe_overage_price_id:
                line_items.append(
                    {
                        "price": plan_limit.stripe_overage_price_id,
                        "quantity": quantity,
                    }
                )
                continue

            unit_amount_cents = int(Decimal(line.unit_amount) * 100)
            if unit_amount_cents <= 0:
                continue

            recurring = {"interval": interval}
            if interval_count > 1:
                recurring["interval_count"] = interval_count

            line_items.append(
                {
                    "price_data": {
                        "currency": currency,
                        "unit_amount": unit_amount_cents,
                        "recurring": recurring,
                        "product_data": {"name": line.description},
                    },
                    "quantity": quantity,
                }
            )

        return line_items

    @classmethod
    def _resolve_customer(cls, *, user, company, company_subscription, subscription_price):
        customer_id = getattr(company_subscription, "stripe_customer_id", None)
        if company_subscription and customer_id:
            try:
                customer = stripe.Customer.retrieve(customer_id)
                return customer, company_subscription
            except stripe.error.InvalidRequestError:
                pass

        customer = stripe.Customer.create(
            email=user.email,
            metadata={
                "user_id": str(user.uid),
                "company_id": str(company.uid),
            },
        )

        if company_subscription is None:
            company_subscription = CompanySubscription.objects.create(
                stripe_customer_id=customer.id,
                status=CompanySubscriptionStatusChoices.PENDING,
                company=company,
                subscription_price=subscription_price,
            )
        else:
            company_subscription.stripe_customer_id = customer.id
            company_subscription.save(update_fields=["stripe_customer_id", "updated_at"])

        return customer, company_subscription

    @classmethod
    @transaction.atomic
    def create_checkout_session(
        cls,
        *,
        user,
        company,
        subscription_price: SubscriptionPrice | None = None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        employee_count: int | None = None,
        user_count: int | None = None,
        include_overage: bool = True,
        coupon_code: str | None = None,
        offer_code: str | None = None,
        referral_code: str | None = None,
        start_trial: bool = False,
        addon_uids: list | None = None,
        addon_codes: list | None = None,
        addon_quantities: dict | None = None,
    ) -> dict:
        guard = PlanChangeGuardService.validate_plan_change(
            company,
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )
        if not guard.allowed:
            raise ValueError(guard.message)

        if referral_code:
            referral_result = ReferralService.validate(referral_code, company=company)
            if not referral_result.valid:
                raise ValueError(referral_result.message)

        subscription_price = BillingPreviewService._resolve_subscription_price(
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )
        coupon_code, offer_validation = OfferService.resolve_coupon_code(
            offer_code=offer_code,
            coupon_code=coupon_code,
            company=company,
            subscription_price=subscription_price,
        )

        try:
            preview = BillingPreviewService.preview(
                company,
                subscription_price=subscription_price,
                subscription_price_slug=subscription_price_slug,
                plan_title=plan_title,
                billing_frequency=billing_frequency,
                employee_count=employee_count,
                user_count=user_count,
                coupon_code=coupon_code,
                addon_uids=addon_uids,
                addon_codes=addon_codes,
                addon_quantities=addon_quantities,
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if not preview:
            raise ValueError("Subscription price not found")

        if not subscription_price.stripe_price_id:
            raise ValueError("Stripe is not configured for this subscription price")

        company_subscription = CompanySubscription.objects.filter(
            company=company,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
        ).first()

        customer, company_subscription = cls._resolve_customer(
            user=user,
            company=company,
            company_subscription=company_subscription,
            subscription_price=subscription_price,
        )

        plan_version = BillingPreviewService._get_target_plan_version(
            subscription_price.subscription,
            company_subscription,
        )
        line_items = cls.build_stripe_line_items(
            preview=preview,
            subscription_price=subscription_price,
            plan_version=plan_version,
            include_overage=include_overage,
        )

        previous_subscription_id = None
        if company_subscription and company_subscription.stripe_subscription_id:
            previous_subscription_id = company_subscription.stripe_subscription_id

        employee_overage = next(
            (
                line
                for line in preview.lines
                if line.line_type == "OVERAGE"
                and line.metadata.get("metric_code") == LimitMetricChoices.EMPLOYEE
            ),
            None,
        )
        user_overage = next(
            (
                line
                for line in preview.lines
                if line.line_type == "OVERAGE"
                and line.metadata.get("metric_code") == LimitMetricChoices.USER
            ),
            None,
        )

        metadata = {
            "user_id": str(user.uid),
            "company_id": str(company.uid),
            "subscription_price_id": str(subscription_price.id),
            "employee_count": str(preview.usage.get(LimitMetricChoices.EMPLOYEE, 0)),
            "user_count": str(preview.usage.get(LimitMetricChoices.USER, 0)),
            "overage_total": str(preview.overage_total),
            "billing_preview_total": str(preview.total),
            "checkout_version": "v2",
        }
        if employee_overage:
            metadata["employee_overage_units"] = str(int(employee_overage.quantity))
        if user_overage:
            metadata["user_overage_units"] = str(int(user_overage.quantity))
        if previous_subscription_id:
            metadata["previous_subscription_id"] = previous_subscription_id
        if coupon_code:
            metadata["coupon_code"] = CouponService._normalize_code(coupon_code)
        if offer_code and offer_validation:
            metadata["offer_code"] = OfferService._normalize_code(offer_code)
        if referral_code:
            metadata["referral_code"] = ReferralService._normalize_code(referral_code)

        resolved_addons = AddOnService.resolve_addons(
            company,
            addon_uids=addon_uids,
            addon_codes=addon_codes,
            quantities=addon_quantities,
            target_subscription=subscription_price.subscription,
            target_plan_version=plan_version,
        )
        if resolved_addons:
            metadata["addon_payload"] = AddOnService.encode_addon_payload(resolved_addons)

        checkout_session_params = {
            "customer": customer.id,
            "payment_method_collection": "if_required",
            "line_items": line_items,
            "mode": "subscription",
            "success_url": (
                f"{os.getenv('BASE_LANDING_FRONTEND_URL')}/payment-success"
                "?success=true&session_id={CHECKOUT_SESSION_ID}"
            ),
            "cancel_url": (
                f"{os.getenv('BASE_LANDING_FRONTEND_URL')}/payment-success?success=false"
            ),
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
        }

        stripe_discounts = []
        if coupon_code:
            coupon_validation = CouponService.validate(
                coupon_code,
                company=company,
                subscription_price=subscription_price,
                existing_plan_discount=Decimal(subscription_price.discount or 0),
            )
            if coupon_validation.valid and coupon_validation.coupon:
                stripe_coupon_id = CouponService.get_or_create_stripe_coupon(
                    coupon_validation.coupon
                )
                if stripe_coupon_id:
                    stripe_discounts.append({"coupon": stripe_coupon_id})
        elif subscription_price.discount and subscription_price.discount > 0:
            coupon_id = cls._create_coupon_for_discount(
                subscription_price.discount,
                discount_kind=subscription_price.discount_kind,
                currency=subscription_price.subscription.currency,
            )
            if coupon_id:
                stripe_discounts.append({"coupon": coupon_id})
                metadata["discount_amount"] = str(subscription_price.discount)
                metadata["discount_kind"] = subscription_price.discount_kind

        if stripe_discounts:
            checkout_session_params["discounts"] = stripe_discounts

        if preview.credit_total > 0:
            credit_coupon_id = cls._create_coupon_for_discount(
                preview.credit_total,
                discount_kind=DiscountKind.FLAT,
                currency=preview.currency,
            )
            if credit_coupon_id:
                checkout_session_params.setdefault("discounts", []).append(
                    {"coupon": credit_coupon_id}
                )
                metadata["credit_applied"] = str(preview.credit_total)

        subscription = subscription_price.subscription
        trial_days = subscription.trial_period or 0
        program_settings = SubscriptionProgramSettings.get_solo()
        if trial_days <= 0 and start_trial:
            trial_days = program_settings.trial_default_days
        if start_trial and trial_days > 0 and not previous_subscription_id:
            checkout_session_params["subscription_data"]["trial_period_days"] = trial_days
            if program_settings.trial_card_required:
                checkout_session_params["payment_method_collection"] = "always"

        checkout_session = stripe.checkout.Session.create(**checkout_session_params)
        logger.info(
            "Created Stripe v2 checkout session id=%s company=%s plan=%s overage=%s",
            checkout_session.id,
            company.uid,
            preview.plan_title,
            preview.overage_total,
        )

        return {
            "checkout_url": checkout_session.url,
            "session_id": checkout_session.id,
            "billing_preview": SubscriptionBillingService._serialize_preview(preview),
        }
