from django.urls import path

from adminio.django_rest.views.subscriptions.v1.plans import (
    AdminSubscriptionPlanList,
    AdminSubscriptionPlanUpdate,
)

urlpatterns = [
    path(
        r"",
        AdminSubscriptionPlanList.as_view(),
        name="adminio.subscription-plan-list",
    ),
    path(
        r"/retrieve/<str:uid>",
        AdminSubscriptionPlanUpdate.as_view(),
        name="adminio.subscription-plan-retrieve",
    ),
]
