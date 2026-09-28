from django.urls import path

from weapi.django_rest.views.subscriptions.v2.addons import (
    PrivateWeSubscriptionAddOnList,
    PrivateWeSubscriptionAddOnPurchase,
)

urlpatterns = [
    path(
        r"/purchase",
        PrivateWeSubscriptionAddOnPurchase.as_view(),
        name="weapi.subscription-addon-purchase",
    ),
    path(
        r"",
        PrivateWeSubscriptionAddOnList.as_view(),
        name="weapi.subscription-addon-list",
    ),
]
