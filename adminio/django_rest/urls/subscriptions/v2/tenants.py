from django.urls import path

from adminio.django_rest.views.subscriptions.v2.tenants import (
    AdminSubscriptionTenantAction,
    AdminSubscriptionTenantDetail,
    AdminSubscriptionTenantEvents,
    AdminSubscriptionTenantList,
)

urlpatterns = [
    path(
        r"/tenants/<uuid:company_uid>/actions",
        AdminSubscriptionTenantAction.as_view(),
        name="adminio.subscription-tenant-action",
    ),
    path(
        r"/tenants/<uuid:company_uid>/events",
        AdminSubscriptionTenantEvents.as_view(),
        name="adminio.subscription-tenant-events",
    ),
    path(
        r"/tenants/<uuid:company_uid>",
        AdminSubscriptionTenantDetail.as_view(),
        name="adminio.subscription-tenant-detail",
    ),
    path(
        r"/tenants",
        AdminSubscriptionTenantList.as_view(),
        name="adminio.subscription-tenant-list",
    ),
]
