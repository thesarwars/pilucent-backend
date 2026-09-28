from django.urls import path

from weapi.django_rest.views.subscriptions.v2.promotions import (
    PrivateWeSubscriptionTrialStart,
    PrivateWeSubscriptionTrialStatus,
)

urlpatterns = [
    path(
        r"/status",
        PrivateWeSubscriptionTrialStatus.as_view(),
        name="weapi.subscription-trial-status-alt",
    ),
    path(
        r"/start",
        PrivateWeSubscriptionTrialStart.as_view(),
        name="weapi.subscription-trial-start-alt",
    ),
]
