import logging
import os
import time
from decimal import Decimal

import stripe
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from paymentio.choices import (
    PaymentInformationStatusChoices,
    PaymentInformationKindChoices,
)
from paymentio.models import PaymentInformation

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import CompanySubscriptionStatusChoices
from subscriptionio.models import CompanySubscription, SubscriptionPrice
from subscriptionio.models import ReferralCode, SubscriptionCoupon
from subscriptionio.choices import SubscriptionEventSourceChoices, SubscriptionEventTypeChoices
from subscriptionio.services.addon_service import AddOnService
from subscriptionio.services.coupon_service import CouponService
from subscriptionio.services.credit_service import CreditService
from subscriptionio.services.dunning_service import DunningService
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.referral_service import ReferralService
from subscriptionio.services.subscription_billing_service import (
    SubscriptionBillingService,
)
from subscriptionio.services.subscription_event_service import SubscriptionEventService
from subscriptionio.services.trial_service import TrialService


stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Use the same logger namespace as StripeAPI so configuration is shared
logger = logging.getLogger("weapi.stripe")


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            os.getenv("STRIPE_WEBHOOK_SECRET"),
        )
        # print("event", event)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    handle_event(event)
    return HttpResponse(status=200)


def _handle_addon_payment_checkout(event_object, metadata):
    from companyio.models import Company

    company = Company.objects.filter(uid=metadata.get("company_id")).first()
    if not company:
        return
    company_subscription = EntitlementService.get_company_subscription(company)
    if not company_subscription:
        return
    addon_payload = metadata.get("addon_payload")
    if addon_payload:
        AddOnService.attach_from_checkout(
            company=company,
            company_subscription=company_subscription,
            addon_payload=addon_payload,
        )
    invalidate_entitlement_cache(company.id)
    SubscriptionEventService.record(
        company=company,
        company_subscription=company_subscription,
        event_type=SubscriptionEventTypeChoices.CHECKOUT_COMPLETED,
        source=SubscriptionEventSourceChoices.WEBHOOK,
        payload={
            "checkout_session_id": event_object.get("id"),
            "checkout_version": "v2_addon",
        },
    )


def handle_event(event):
    event_obejct = event["data"]["object"]
    event_type = event["type"]

    if event_type == "checkout.session.completed":
        handle_checkout_completed(event_obejct)
        return

    if event_type == "invoice.payment_succeeded":
        time.sleep(5)  # Wait for a few seconds to ensure data consistency
        handle_invoice_payment_succeeded(event_obejct)
        return

    if event_type == "invoice.payment_failed":
        handle_invoice_payment_failed(event_obejct)
        return

    if event_type == "customer.subscription.updated":
        handle_subscription_updated(event_obejct)
        return


def handle_checkout_completed(event_object):
    if PaymentInformation.objects.filter(
        payment_intent_id=event_object.get("id"),
        status=PaymentInformationStatusChoices.SUCCEEDED,
    ).exists():
        return

    metadata = event_object.get("metadata") or {}
    if metadata.get("checkout_version") == "v2_addon":
        _handle_addon_payment_checkout(event_object, metadata)
        return
    customer_id = event_object.get("customer")
    company_subscription = CompanySubscription.objects.get(
        stripe_customer_id=customer_id,
    )
    previous_subscription_id = getattr(company_subscription, "stripe_subscription_id", None)
    # user = company_subscription.created_by
    amount_paid = event_object.get("amount_total") / 100
    new_stripe_subscription_id = event_object.get("subscription")
    stripe_subscription = stripe.Subscription.retrieve(new_stripe_subscription_id)

    try:
        if previous_subscription_id and previous_subscription_id != event_object["subscription"]:
            stripe.Subscription.cancel(previous_subscription_id)
            logger.info(
                "Cancelled previous Stripe subscription during plan change",
                extra={
                    "company": getattr(company_subscription, "uid", None),
                    "previous_subscription_id": previous_subscription_id,
                    "new_subscription_id": event_object["subscription"],
                },
            )
    except Exception:
        logger.exception(
            "Failed to cancel previous Stripe subscription",
            extra={
                "company": getattr(company_subscription, "uid", None),
                "previous_subscription_id": previous_subscription_id,
            },
        )
    subscription_price_id = metadata.get("subscription_price_id")
    if subscription_price_id:
        subscription_price = SubscriptionPrice.objects.filter(
            id=subscription_price_id
        ).first()
        if subscription_price:
            company_subscription.subscription_price = subscription_price

    company_subscription.stripe_subscription_id = new_stripe_subscription_id
    SubscriptionBillingService.sync_stripe_subscription_period(
        company_subscription, stripe_subscription
    )

    stripe_status = stripe_subscription.get("status")
    if stripe_status == "trialing":
        company_subscription.status = CompanySubscriptionStatusChoices.TRIALING
        trial_end = stripe_subscription.get("trial_end")
        if trial_end:
            company_subscription.trial_end = SubscriptionBillingService._as_aware_datetime(
                trial_end
            )
        company_subscription.trial_start = company_subscription.current_period_start
    else:
        company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        company_subscription.trial_start = None
        company_subscription.trial_end = None

    coupon_code = metadata.get("coupon_code")
    if coupon_code:
        coupon = SubscriptionCoupon.objects.filter(code__iexact=coupon_code).first()
        if coupon:
            company_subscription.applied_coupon = coupon
            CouponService.redeem(
                coupon,
                company=company_subscription.company,
                redeemed_by=company_subscription.created_by,
                checkout_session_id=event_object.get("id"),
                discount_amount=Decimal(str(metadata.get("coupon_discount", "0"))),
            )

    referral_code = metadata.get("referral_code")
    if referral_code:
        referral = ReferralCode.objects.filter(code__iexact=referral_code).first()
        if referral:
            ReferralService.redeem(referral, referred_company=company_subscription.company)

    company_subscription.save(
        update_fields=[
            "stripe_subscription_id",
            "status",
            "subscription_price",
            "trial_start",
            "trial_end",
            "applied_coupon",
            "updated_at",
        ]
    )
    invalidate_entitlement_cache(company_subscription.company_id)

    addon_payload = metadata.get("addon_payload")
    if addon_payload:
        AddOnService.attach_from_checkout(
            company=company_subscription.company,
            company_subscription=company_subscription,
            addon_payload=addon_payload,
        )

    credit_applied = metadata.get("credit_applied")
    if credit_applied:
        CreditService.apply_credits(
            company_subscription.company,
            Decimal(str(credit_applied)),
            source_ref=event_object.get("id") or "",
        )

    SubscriptionEventService.record(
        company=company_subscription.company,
        company_subscription=company_subscription,
        event_type=SubscriptionEventTypeChoices.CHECKOUT_COMPLETED,
        new_status=company_subscription.status,
        source=SubscriptionEventSourceChoices.WEBHOOK,
        payload={"checkout_session_id": event_object.get("id")},
    )

    invoice_id = event_object.get("invoice")
    invoice = stripe.Invoice.retrieve(invoice_id) if invoice_id else None

    payment_information = None
    if invoice:
        try:
            payment_information = PaymentInformation.objects.create(
                company=company_subscription.company,
                payment_intent_id=event_object["id"],
                subscription_price=company_subscription.subscription_price,
                status=PaymentInformationStatusChoices.PENDING,
                amount=amount_paid,
                currency=company_subscription.subscription_price.subscription.currency,
                kind=PaymentInformationKindChoices.COMPANY_SUBSCRIPTION,
                stripe_invoice_id=invoice.id,
                stripe_invoice_url=invoice.hosted_invoice_url,
            )
            SubscriptionBillingService.upsert_invoice_from_stripe(
                company_subscription=company_subscription,
                stripe_invoice=invoice,
                payment_information=payment_information,
            )
            logger.info(
                "Created PaymentInformation for company=%s",
                company_subscription.company.name,
            )
        except Exception as e:
            logger.error(
                "Error creating PaymentInformation for company: %s, invoice: %s, error: %s",
                company_subscription.company.name,
                invoice.id,
                str(e),
            )

    # Cancel any previous Stripe subscription associated with this company
    # previous_subscription_id = metadata.get("previous_subscription_id")
    # if previous_subscription_id and previous_subscription_id != new_stripe_subscription_id:
    #     try:
    #         stripe.Subscription.delete(previous_subscription_id)
    #         logger.info(
    #             "Cancelled previous Stripe subscription=%s for company=%s",
    #             previous_subscription_id,
    #             company_subscription.company.name,
    #         )
    #     except Exception as e:
    #         logger.error(
    #             "Failed to cancel previous Stripe subscription=%s for company=%s, error=%s",
    #             previous_subscription_id,
    #             company_subscription.company.name,
    #             str(e),
    #         )


def handle_invoice_payment_succeeded(invoice):
    billing_reason = invoice.get("billing_reason")
    if billing_reason == "subscription_create":
        payment = PaymentInformation.objects.filter(
            stripe_invoice_id=invoice["id"]
        ).first()

        if not payment:
            return

        if payment.status == PaymentInformationStatusChoices.SUCCEEDED:
            return

        payment.status = PaymentInformationStatusChoices.SUCCEEDED
        payment.save(update_fields=["status"])
        company_subscription = CompanySubscription.objects.filter(
            company=payment.company,
        ).first()
        if company_subscription:
            SubscriptionBillingService.upsert_invoice_from_stripe(
                company_subscription=company_subscription,
                stripe_invoice=invoice,
                payment_information=payment,
            )

        logger.info(
            "Updated PaymentInformation to SUCCEEDED for invoice=%s, company=%s",
            invoice["id"],
            payment.company.name,
        )
    if billing_reason == "subscription_cycle":
        payment = PaymentInformation.objects.filter(
            stripe_invoice_id=invoice["id"]
        ).first()

        if payment and payment.status == PaymentInformationStatusChoices.SUCCEEDED:
            return

        if not payment:
            customer_id = invoice.get("customer")

            try:
                company_subscription = CompanySubscription.objects.get(
                    stripe_customer_id=customer_id,
                )
                if company_subscription.status in {
                    CompanySubscriptionStatusChoices.PAST_DUE,
                    CompanySubscriptionStatusChoices.GRACE,
                    CompanySubscriptionStatusChoices.SUSPENDED,
                }:
                    DunningService.record_payment_recovery(
                        company_subscription,
                        source=SubscriptionEventSourceChoices.WEBHOOK,
                        payload={"stripe_invoice_id": invoice["id"]},
                    )
                else:
                    company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
                    company_subscription.save(update_fields=["status", "updated_at"])
                    invalidate_entitlement_cache(company_subscription.company_id)
                if company_subscription.stripe_subscription_id:
                    stripe_subscription = stripe.Subscription.retrieve(
                        company_subscription.stripe_subscription_id
                    )
                    SubscriptionBillingService.sync_stripe_subscription_period(
                        company_subscription, stripe_subscription
                    )
                logger.info(
                    "Updated CompanySubscription to ACTIVE for company=%s based on invoice=%s",
                    company_subscription.company.name,
                    invoice["id"],
                )
                payment = PaymentInformation.objects.create(
                    company=company_subscription.company,
                    payment_intent_id=invoice.get("payment_intent") or invoice["id"],
                    subscription_price=company_subscription.subscription_price,
                    status=PaymentInformationStatusChoices.SUCCEEDED,
                    amount=invoice["amount_paid"] / 100,
                    currency=company_subscription.subscription_price.subscription.currency,
                    kind=PaymentInformationKindChoices.COMPANY_SUBSCRIPTION,
                    stripe_invoice_id=invoice["id"],
                    stripe_invoice_url=invoice["hosted_invoice_url"],
                )
                SubscriptionBillingService.upsert_invoice_from_stripe(
                    company_subscription=company_subscription,
                    stripe_invoice=invoice,
                    payment_information=payment,
                )
                logger.info(
                    "Created PaymentInformation for company=%s based on invoice=%s",
                    company_subscription.company.name,
                    invoice["id"],
                )
            except CompanySubscription.DoesNotExist:
                logger.warning(
                    "CompanySubscription not found for customer_id=%s while processing invoice=%s",
                    customer_id,
                    invoice["id"],
                )
                return
        # payment.status = PaymentInformationStatusChoices.SUCCEEDED
        # payment.save(update_fields=["status"])

        logger.info(
            "Updated PaymentInformation to SUCCEEDED for invoice=%s, company=%s",
            invoice["id"],
            payment.company.name,
        )


def handle_invoice_payment_failed(invoice):
    try:
        payment_info = PaymentInformation.objects.get(
            stripe_invoice_id=invoice["id"],
        )
    except PaymentInformation.DoesNotExist:
        return

    payment_info.status = PaymentInformationStatusChoices.FAILED
    payment_info.save(update_fields=["status"])
    logger.info(
        "Updated PaymentInformation to FAILED for invoice=%s, company=%s",
        invoice["id"],
        payment_info.company.name,
    )

    company_subscription = CompanySubscription.objects.filter(
        company=payment_info.company,
    ).first()
    if company_subscription:
        DunningService.record_payment_failure(
            company_subscription,
            source=SubscriptionEventSourceChoices.WEBHOOK,
            payload={"stripe_invoice_id": invoice["id"]},
        )
        SubscriptionBillingService.upsert_invoice_from_stripe(
            company_subscription=company_subscription,
            stripe_invoice=invoice,
            payment_information=payment_info,
        )


def handle_subscription_updated(stripe_subscription):
    customer_id = stripe_subscription.get("customer")
    if not customer_id:
        return

    company_subscription = CompanySubscription.objects.filter(
        stripe_customer_id=customer_id,
    ).first()
    if not company_subscription:
        return

    SubscriptionBillingService.sync_stripe_subscription_period(
        company_subscription, stripe_subscription
    )

    stripe_status = stripe_subscription.get("status")
    if stripe_status == "trialing":
        company_subscription.status = CompanySubscriptionStatusChoices.TRIALING
        trial_end = stripe_subscription.get("trial_end")
        if trial_end:
            company_subscription.trial_end = SubscriptionBillingService._as_aware_datetime(
                trial_end
            )
        company_subscription.trial_start = company_subscription.current_period_start
    elif stripe_status == "active":
        TrialService.convert_to_paid(company_subscription)
        return
    elif stripe_status in {"canceled", "unpaid", "incomplete_expired"}:
        previous_status = company_subscription.status
        company_subscription.status = CompanySubscriptionStatusChoices.CANCELED
        company_subscription.canceled_at = timezone.now()
        company_subscription.cancel_at_period_end = False
        SubscriptionEventService.record(
            company=company_subscription.company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.SUBSCRIPTION_CANCELED,
            previous_status=previous_status,
            new_status=company_subscription.status,
            source=SubscriptionEventSourceChoices.WEBHOOK,
        )
    elif stripe_status == "past_due":
        company_subscription.status = CompanySubscriptionStatusChoices.PAST_DUE

    company_subscription.save(
        update_fields=[
            "status",
            "trial_start",
            "trial_end",
            "canceled_at",
            "cancel_at_period_end",
            "updated_at",
        ]
    )
    EntitlementService.invalidate(company_subscription.company_id)
