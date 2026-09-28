from django.urls import path

from weapi.django_rest.views.subscriptions.v2.promotions import (
    PrivateWeSubscriptionOfferList,
    PrivateWeSubscriptionReferralCode,
    PrivateWeSubscriptionTrialStart,
    PrivateWeSubscriptionTrialStatus,
    PrivateWeSubscriptionValidateCoupon,
    PrivateWeSubscriptionValidateOffer,
)

urlpatterns = [
    path(
        r"/validate-coupon",
        PrivateWeSubscriptionValidateCoupon.as_view(),
        name="weapi.subscription-validate-coupon",
    ),
    path(
        r"/validate-offer",
        PrivateWeSubscriptionValidateOffer.as_view(),
        name="weapi.subscription-validate-offer",
    ),
    path(
        r"/offers",
        PrivateWeSubscriptionOfferList.as_view(),
        name="weapi.subscription-offers",
    ),
    path(
        r"/referral",
        PrivateWeSubscriptionReferralCode.as_view(),
        name="weapi.subscription-referral-code",
    ),
    path(
        r"/trial/status",
        PrivateWeSubscriptionTrialStatus.as_view(),
        name="weapi.subscription-trial-status",
    ),
    path(
        r"/trial/start",
        PrivateWeSubscriptionTrialStart.as_view(),
        name="weapi.subscription-trial-start",
    ),
]
