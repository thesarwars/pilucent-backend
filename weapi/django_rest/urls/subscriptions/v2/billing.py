from django.urls import path

from weapi.django_rest.views.subscriptions.v2.billing import (
    PrivateWeSubscriptionCurrent,
    PrivateWeSubscriptionInvoiceDetail,
    PrivateWeSubscriptionInvoiceList,
    PrivateWeSubscriptionPreview,
    PrivateWeSubscriptionUsage,
)

urlpatterns = [
    path(
        r"/usage",
        PrivateWeSubscriptionUsage.as_view(),
        name="weapi.subscription-usage",
    ),
    path(
        r"/current",
        PrivateWeSubscriptionCurrent.as_view(),
        name="weapi.subscription-current",
    ),
    path(
        r"/preview",
        PrivateWeSubscriptionPreview.as_view(),
        name="weapi.subscription-preview",
    ),
    path(
        r"/invoices/<uuid:uid>",
        PrivateWeSubscriptionInvoiceDetail.as_view(),
        name="weapi.subscription-invoice-detail",
    ),
    path(
        r"/invoices",
        PrivateWeSubscriptionInvoiceList.as_view(),
        name="weapi.subscription-invoice-list",
    ),
]
