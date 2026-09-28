import os, stripe, logging

from subscriptionio.choices import SubscriptionPriceBillingFrequencyChoices

logger = logging.getLogger(__name__)


def complete_stripe_payment(data):
    logger.info("Stripe payment has been started...")
    # Set your API key
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

    # Create a PaymentIntent with the order amount and currency
    intent = stripe.PaymentIntent.create(
        amount=round(100 * data["total"]),
        currency=data["currency"],
        automatic_payment_methods={"enabled": True},
        metadata=data,
    )
    logger.info("Has been completed stipe payment...")
    return intent


def get_stripe_payment(payment_intent_id):
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    return stripe.PaymentIntent.retrieve(payment_intent_id)


def get_subscription_period(period):
    return {
        SubscriptionPriceBillingFrequencyChoices.YEARLY: 12,
        SubscriptionPriceBillingFrequencyChoices.HALF_YEARLY: 6,
        SubscriptionPriceBillingFrequencyChoices.QUARTERLY: 3,
        SubscriptionPriceBillingFrequencyChoices.MONTHLY: 1,
    }.get(period)
