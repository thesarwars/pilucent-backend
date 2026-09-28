from django.urls import path

from adminio.django_rest.views.subscriptions.v2.invoices import (
    AdminSubscriptionInvoiceDetail,
    AdminSubscriptionInvoiceList,
    AdminSubscriptionInvoiceRefund,
    AdminSubscriptionInvoiceRetry,
)

urlpatterns = [
    path(
        r"/invoices/<uuid:uid>/retry",
        AdminSubscriptionInvoiceRetry.as_view(),
        name="adminio.subscription-invoice-retry",
    ),
    path(
        r"/invoices/<uuid:uid>/refund",
        AdminSubscriptionInvoiceRefund.as_view(),
        name="adminio.subscription-invoice-refund",
    ),
    path(
        r"/invoices/<uuid:uid>",
        AdminSubscriptionInvoiceDetail.as_view(),
        name="adminio.subscription-invoice-detail",
    ),
    path(
        r"/invoices",
        AdminSubscriptionInvoiceList.as_view(),
        name="adminio.subscription-invoice-list",
    ),
]
