from django.urls import path

from adminio.django_rest.views.subscriptions.v2.addons import (
    AdminSubscriptionAddOnDetail,
    AdminSubscriptionAddOnListCreate,
)

urlpatterns = [
    path(
        r"/addons/<uuid:uid>",
        AdminSubscriptionAddOnDetail.as_view(),
        name="adminio.subscription-addon-detail",
    ),
    path(
        r"/addons",
        AdminSubscriptionAddOnListCreate.as_view(),
        name="adminio.subscription-addon-list",
    ),
]
