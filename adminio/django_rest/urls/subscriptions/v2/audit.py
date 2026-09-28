from django.urls import path

from adminio.django_rest.views.subscriptions.v2.audit import (
    AdminSubscriptionAuditLogList,
)

urlpatterns = [
    path(
        r"/audit-logs",
        AdminSubscriptionAuditLogList.as_view(),
        name="adminio.subscription-audit-logs",
    ),
]
