from django.urls import path

from adminio.django_rest.views.subscriptions.v2.plans import (
    AdminSubscriptionPlanDetail,
    AdminSubscriptionPlanListCreate,
)

urlpatterns = [
    path(
        r"/plans/<uuid:uid>",
        AdminSubscriptionPlanDetail.as_view(),
        name="adminio.subscription-plan-detail",
    ),
    path(
        r"/plans",
        AdminSubscriptionPlanListCreate.as_view(),
        name="adminio.subscription-plan-catalog",
    ),
]
