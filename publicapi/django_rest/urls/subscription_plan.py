from django.urls import path, include

from ..views.subscription_plan import PublicSubscriptionList, PublicSubscriptionDetails, PublicSubscriptionPriceList

urlpatterns = [
    path(
        r"/<slug:slug>/prices",
        PublicSubscriptionPriceList.as_view(),
        name="publicapi.subscription-plan-price-list",
    ),
    path(
        r"/<slug:slug>",
        PublicSubscriptionDetails.as_view(),
        name="publicapi.subscription-plan-details",
    ),
    path(
        r"", PublicSubscriptionList.as_view(), name="publicapi.subscription-plan-list"
    ),
]
