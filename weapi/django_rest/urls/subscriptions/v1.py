from django.urls import path

from weapi.django_rest.helpers.stripe_webhook import stripe_webhook
from weapi.django_rest.views.subscriptions.v1.checkout import StripeAPI
from weapi.django_rest.views.subscriptions.v1.payment_information import (
    PrivateWeSubscriptionPaymentInformationDetails,
    PrivateWeSubscriptionPaymentInformationList,
)

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeSubscriptionPaymentInformationDetails.as_view(),
        name="weapi.subscription-payment-information-details",
    ),
    path(
        r"",
        PrivateWeSubscriptionPaymentInformationList.as_view(),
        name="weapi.subscription-payment-information-list",
    ),
    path(
        r"/checkout",
        StripeAPI.CreateStripeCheckoutSession.as_view(),
        name="weapi.subscription-checkout",
        # api/v1/we/subscriptions/checkout
    ),
    path(
        r"/stripe/webhook/j12t34",
        stripe_webhook,
        name="weapi.subscription-stripe-webhook",
        # api/v1/we/subscriptions/stripe/webhook/j12t34
    ),
]
