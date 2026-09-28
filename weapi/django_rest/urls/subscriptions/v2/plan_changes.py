from django.urls import path

from weapi.django_rest.views.subscriptions.v2.plan_changes import (
    PrivateWeSubscriptionPlanChangePreview,
    PrivateWeSubscriptionScheduleDowngrade,
    PrivateWeSubscriptionScheduledPlanChange,
)

urlpatterns = [
    path(
        r"/preview",
        PrivateWeSubscriptionPlanChangePreview.as_view(),
        name="weapi.subscription-plan-change-preview",
    ),
    path(
        r"/scheduled",
        PrivateWeSubscriptionScheduledPlanChange.as_view(),
        name="weapi.subscription-scheduled-plan-change",
    ),
    path(
        r"/schedule-downgrade",
        PrivateWeSubscriptionScheduleDowngrade.as_view(),
        name="weapi.subscription-schedule-downgrade",
    ),
]
