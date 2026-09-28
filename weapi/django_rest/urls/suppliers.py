from django.urls import path

from weapi.django_rest.views.suppliers import (
    PrivateWeSupplierList,
    PrivateWeSupplierDetails,
    PrivateWeSupplierBulkCreate,
    PrivateWeSupplierFileDetails,
    PrivateWeSupplierFileList,
    PrivateWeSupplierTransactionList,
    PrivateWeSupplierPurchaseList,
)

urlpatterns = [
    path(
        r"/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWeSupplierFileDetails.as_view(),
        name="weapi.supplier-file-detils",
    ),
    path(
        r"/<uuid:uid>/files",
        PrivateWeSupplierFileList.as_view(),
        name="weapi.supplier-file-list",
    ),
    # path(
    #     r"/<uuid:uid>/purchases",
    #     PrivateWeSupplierPurchaseList.as_view(),
    #     name="weapi.suppliers-purchase-list",
    # ),
    path(
        r"/<uuid:uid>/transactions",
        PrivateWeSupplierTransactionList.as_view(),
        name="weapi.suppliers-transactions",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeSupplierDetails.as_view(),
        name="weapi.suppliers.details",
    ),
    path(
        r"/bulk-create",
        PrivateWeSupplierBulkCreate.as_view(),
        name="weapi.suppliers.bulk-create",
    ),
    path(
        r"",
        PrivateWeSupplierList.as_view(),
        name="weapi.suppliers.list",
    ),
]
