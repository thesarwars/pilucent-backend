from django.urls import path

from weapi.django_rest.views.subscriptions.v2.checkout import (
    PrivateWeSubscriptionCheckoutV2,
)

urlpatterns = [
    path(
        r"",
        PrivateWeSubscriptionCheckoutV2.as_view(),
        name="weapi.subscription-checkout-v2",
    ),
]
