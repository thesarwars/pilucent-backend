from django.urls import path

from publicapi.django_rest.views.subscriptions.v2.plans import (
    PublicSubscriptionPlanDetail,
    PublicSubscriptionPlanList,
    PublicSubscriptionPlanPreview,
)

urlpatterns = [
    path(
        r"/preview",
        PublicSubscriptionPlanPreview.as_view(),
        name="publicapi.subscription-plan-v2-preview",
    ),
    path(
        r"/<slug:slug>",
        PublicSubscriptionPlanDetail.as_view(),
        name="publicapi.subscription-plan-v2-detail",
    ),
    path(
        r"",
        PublicSubscriptionPlanList.as_view(),
        name="publicapi.subscription-plan-v2-list",
    ),
]
