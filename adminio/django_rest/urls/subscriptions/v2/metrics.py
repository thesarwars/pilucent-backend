from django.urls import path

from adminio.django_rest.views.subscriptions.v2.metrics import (
    AdminSubscriptionMetricDetail,
    AdminSubscriptionMetricListCreate,
)

urlpatterns = [
    path(
        r"/metrics/<uuid:uid>",
        AdminSubscriptionMetricDetail.as_view(),
        name="adminio.subscription-metric-detail",
    ),
    path(
        r"/metrics",
        AdminSubscriptionMetricListCreate.as_view(),
        name="adminio.subscription-metric-catalog",
    ),
]
