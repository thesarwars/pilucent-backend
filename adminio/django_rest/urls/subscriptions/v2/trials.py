from django.urls import path

from adminio.django_rest.views.subscriptions.v2.trials import (
    AdminSubscriptionTrialAction,
    AdminSubscriptionTrialList,
    AdminSubscriptionTrialSettings,
)

urlpatterns = [
    path(
        r"/trials/settings",
        AdminSubscriptionTrialSettings.as_view(),
        name="adminio.subscription-trial-settings",
    ),
    path(
        r"/trials",
        AdminSubscriptionTrialList.as_view(),
        name="adminio.subscription-trial-list",
    ),
    path(
        r"/trials/<uuid:company_uid>/actions",
        AdminSubscriptionTrialAction.as_view(),
        name="adminio.subscription-trial-action",
    ),
]
