import logging
import os
import uuid

import stripe
from django.conf import settings
from django.db import transaction
from rest_framework import response, views

from common.choices import DiscountKind
from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
)
from subscriptionio.models import CompanySubscription, SubscriptionPrice

from weapi.django_rest.helpers.billing import resolve_billing_company

class StripeAPI:
    logger = logging.getLogger("weapi.stripe")
    stripe.api_key = settings.STRIPE_SECRET_KEY

    class CreateStripeCheckoutSession(views.APIView):
        logger = logging.getLogger("weapi.stripe")

        @transaction.atomic
        def post(self, request, *args, **kwargs):
            plan_title = request.data.get("plan_title")
            billing_frequency = request.data.get("billing_frequency")
            user = request.user

            company = resolve_billing_company(request)

            # Reuse existing company subscription and Stripe customer if present
            company_subscription = CompanySubscription.objects.filter(
                company=company,
                kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            ).first()
            subscription_price = SubscriptionPrice.objects.filter(
                subscription__title=plan_title, billing_frequency=billing_frequency
            ).first()

            if not subscription_price:
                self.logger.warning(
                    "Subscription price not found for plan_title=%s, billing_frequency=%s",
                    plan_title,
                    billing_frequency,
                )
                return response.Response(
                    {"error": "Subscription price not found."}, status=404
                )

            customer_id = getattr(company_subscription, "stripe_customer_id", None)
            if company_subscription and customer_id:
                # Reuse existing Stripe customer
                try:
                    customer = stripe.Customer.retrieve(customer_id)
                except stripe.error.InvalidRequestError:
                    # If the stored customer id is invalid, create a new one
                    customer = stripe.Customer.create(
                        email=user.email,
                        metadata={
                            "user_id": str(user.uid),
                            "company_id": str(company.uid),
                        },
                    )
                    company_subscription.stripe_customer_id = customer.id
                    company_subscription.save(update_fields=["stripe_customer_id"])
            else:
                # First time: create Stripe customer and (if needed) a CompanySubscription
                customer = stripe.Customer.create(
                    email=user.email,
                    metadata={
                        "user_id": str(user.uid),
                        "company_id": str(company.uid),
                    },
                )

                if company_subscription is None:
                    CompanySubscription.objects.create(
                        stripe_customer_id=customer.id,
                        status=CompanySubscriptionStatusChoices.PENDING,
                        # created_by=user,
                        company=company,
                        subscription_price=subscription_price,
                    )
                else:
                    company_subscription.stripe_customer_id = customer.id
                    company_subscription.save(update_fields=["stripe_customer_id"])

            # Track any existing Stripe subscription so it can be cancelled
            # after the new subscription is successfully created.
            previous_subscription_id = None
            stripe_subscription_id = getattr(
                company_subscription, "stripe_subscription_id", None
            )
            if company_subscription and stripe_subscription_id:
                previous_subscription_id = stripe_subscription_id

            checkout_session_params = {
                "customer": customer.id,
                "payment_method_collection": "if_required",
                "line_items": [
                    {
                        "price": subscription_price.stripe_price_id,
                        "quantity": 1,
                    }
                ],
                "mode": "subscription",
                "success_url": f"{os.getenv('BASE_LANDING_FRONTEND_URL')}/payment-success?success=true&session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{os.getenv('BASE_LANDING_FRONTEND_URL')}/payment-success?success=false",
                "metadata": {
                    "user_id": str(user.uid),
                    "company_id": str(company.uid),
                    "subscription_price_id": str(subscription_price.id),
                },
            }

            # For plan changes, include the previous subscription so the
            # webhook can cancel it after the new one is active.
            if previous_subscription_id:
                checkout_session_params["metadata"][
                    "previous_subscription_id"
                ] = previous_subscription_id

            if subscription_price.discount and subscription_price.discount > 0:
                discount_kind = getattr(subscription_price, "discount_kind", "flat")
                self.logger.info(
                    "Applying discount. kind=%s, amount=%s",
                    discount_kind,
                    subscription_price.discount,
                )
                coupon_id = self._create_coupon_for_discount(
                    subscription_price.discount,
                    discount_kind=discount_kind,
                    currency=subscription_price.subscription.currency,
                )
                if coupon_id:
                    checkout_session_params["discounts"] = [{"coupon": coupon_id}]
                    checkout_session_params["metadata"]["discount_amount"] = str(
                        subscription_price.discount
                    )
                    checkout_session_params["metadata"]["discount_kind"] = discount_kind
            checkout_session = stripe.checkout.Session.create(**checkout_session_params)

            self.logger.info(
                "Created Stripe checkout session id=%s for company=%s user=%s plan_title=%s",
                checkout_session.id,
                company.uid,
                user.uid,
                plan_title,
            )
            # CompanySubscription is created only once above; later upgrades/downgrades
            # reuse the same record and Stripe customer, so we do not create a new
            # CompanySubscription here.

            return response.Response(
                {
                    "checkout_url": checkout_session.url,
                    "session_id": checkout_session.id,
                },
            )

        def _create_coupon_for_discount(
            self, discount, discount_kind=DiscountKind.FLAT, currency="USD"
        ):
            # discount = subscription_price.discount
            coupon_id = f"DISCOUNT_{uuid.uuid4().hex[:8].upper()}"
            self.logger.info("Creating coupon with ID=%s", coupon_id)
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
                elif discount_kind == DiscountKind.FLAT:
                    amount_off = int(discount * 100)  # amount in cents
                    coupon = stripe.Coupon.create(
                        id=coupon_id,
                        amount_off=amount_off,  # amount in cents
                        currency=currency.lower(),
                        duration="once",
                        metadata={"source": "subscription_flat_discount"},
                    )
                self.logger.info(
                    "Created coupon id=%s for discount_kind=%s, discount=%s",
                    coupon.id,
                    discount_kind,
                    discount,
                )
                return coupon.id
            except Exception as e:
                self.logger.error("Error creating coupon: %s", str(e))
                return None
