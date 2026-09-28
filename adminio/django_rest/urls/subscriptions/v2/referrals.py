from django.urls import path

from adminio.django_rest.views.subscriptions.v2.referrals import (
    AdminSubscriptionReferralAction,
    AdminSubscriptionReferralActivity,
    AdminSubscriptionReferralSettings,
)

urlpatterns = [
    path(
        r"/referrals/settings",
        AdminSubscriptionReferralSettings.as_view(),
        name="adminio.subscription-referral-settings",
    ),
    path(
        r"/referrals/activity",
        AdminSubscriptionReferralActivity.as_view(),
        name="adminio.subscription-referral-activity",
    ),
    path(
        r"/referrals/<uuid:uid>/actions",
        AdminSubscriptionReferralAction.as_view(),
        name="adminio.subscription-referral-action",
    ),
]
