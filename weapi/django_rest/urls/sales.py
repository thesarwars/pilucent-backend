from django.urls import path

from ..views.sales import (
    PrivateWeSalesDocumentList,
    PrivateWeSaleList,
    PrivateWeSaleDetails,
    PrivateWeSalesItemList,
    PrivateWeSalesItemDetails,
    PrivateWeSaleTagList,
    PrivateWeSaleFileItemList,
    PrivateWeSalesFileItemDetails,
    PrivateWeSalePaymentReceiveList,
    PrivateWeSalePaymentReceiveDetails,
    PrivateWeSalePaymentReceiveItemList,
    PrivateWeSalePaymentReceiveFileItemList,
    PrivateWeSalesPaymentReceiveFileItemDetails,
    PrivateWeSellSettingDetails,
    PrivateWeSalesTaxCreateList,
    InvoiceDashboardOverview,
)

urlpatterns = [
    path(
        r"/documents",
        PrivateWeSalesDocumentList.as_view(),
        name="weapi.sales-document-list",
    ),
    path(
        r"/dashboard/overview",
        InvoiceDashboardOverview.as_view(),
        name="weapi.invoice-dashboard-overview",
    ),
    # Setting related
    path(
        r"/settings",
        PrivateWeSellSettingDetails.as_view(),
        name="weapi.sale-setting-details",
    ),
    # sales tax related
    path(
        r"/taxes",
        PrivateWeSalesTaxCreateList.as_view(),
        name="weapi.sales-tax-list",
    ),
    # Sell payment receve related
    path(
        r"/payment-received/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWeSalesPaymentReceiveFileItemDetails.as_view(),
        name="weapi.sale-payment-received-file-details",
    ),
    path(
        r"/payment-received/<uuid:uid>/files",
        PrivateWeSalePaymentReceiveFileItemList.as_view(),
        name="weapi.sale-payment-received-files",
    ),
    path(
        r"/payment-received/<uuid:uid>/items",
        PrivateWeSalePaymentReceiveItemList.as_view(),
        name="weapi.sale-payment-received-items",
    ),
    path(
        r"/payment-received/<uuid:uid>",
        PrivateWeSalePaymentReceiveDetails.as_view(),
        name="weapi.sale-payment-received-details",
    ),
    path(
        r"/payment-received",
        PrivateWeSalePaymentReceiveList.as_view(),
        name="weapi.sale-payment-received",
    ),
    # Sell related
    path(
        r"/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWeSalesFileItemDetails.as_view(),
        name="weapi.creditnote-file-details",
    ),
    path(
        r"/<uuid:uid>/files",
        PrivateWeSaleFileItemList.as_view(),
        name="weapi.sale-file-item-list",
    ),
    path(
        r"/<uuid:uid>/tags",
        PrivateWeSaleTagList.as_view(),
        name="weapi.sale-tag-list",
    ),
    path(
        r"/<uuid:uid>/items/<uuid:sale_item_uid>",
        PrivateWeSalesItemDetails.as_view(),
        name="weapi.sales-item-details",
    ),
    path(
        r"/<uuid:uid>/items",
        PrivateWeSalesItemList.as_view(),
        name="weapi.sales-item-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeSaleDetails.as_view(),
        name="weapi.sale-details",
    ),
    path(r"", PrivateWeSaleList.as_view(), name="weapi.sale-list"),
]
