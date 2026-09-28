from django.urls import path

from weapi.django_rest.views.subscriptions.v2.lifecycle import (
    PrivateWeSubscriptionAcceptRetentionOffer,
    PrivateWeSubscriptionCancel,
    PrivateWeSubscriptionEventTimeline,
    PrivateWeSubscriptionLifecycleState,
    PrivateWeSubscriptionReactivate,
    PrivateWeSubscriptionRetentionOffers,
)

urlpatterns = [
    path(
        r"/state",
        PrivateWeSubscriptionLifecycleState.as_view(),
        name="weapi.subscription-lifecycle-state",
    ),
    path(
        r"/cancel",
        PrivateWeSubscriptionCancel.as_view(),
        name="weapi.subscription-cancel",
    ),
    path(
        r"/retention-offers",
        PrivateWeSubscriptionRetentionOffers.as_view(),
        name="weapi.subscription-retention-offers",
    ),
    path(
        r"/accept-retention-offer",
        PrivateWeSubscriptionAcceptRetentionOffer.as_view(),
        name="weapi.subscription-accept-retention-offer",
    ),
    path(
        r"/reactivate",
        PrivateWeSubscriptionReactivate.as_view(),
        name="weapi.subscription-reactivate",
    ),
    path(
        r"/events",
        PrivateWeSubscriptionEventTimeline.as_view(),
        name="weapi.subscription-events",
    ),
]
