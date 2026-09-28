from django.urls import path

from ..views.purchases import (
    PrivateWePurchaseList,
    PrivateWePurchaseDetails,
    PrivateWePurchaseItemList,
    PrivateWePurchaseItemDetails,
    PrivateWePurchaseTagList,
    PrivateWePurchaseFileItemList,
    PrivateWePurchaseFileItemDetails,
    PrivateWePurchasePaymentList,
    PrivateWePurchasePaymentDetails,
    PrivateWePurchasePaymentItemsList,
    PrivateWePurchasePaymentItemDetails,
    PrivateWePurchasePaymentTagList,
    PrivateWePurchasePaymentFileItemList,
    PrivateWePurchasePaymentFileItemDetails,
    PrivateWePurchaseSettingDetails,
)

urlpatterns = [
    # Setting related
    path(
        r"/settings",
        PrivateWePurchaseSettingDetails.as_view(),
        name="weapi.purchase-setting-details",
    ),
    # Purchase payment related
    path(
        r"/payments/<uuid:uid>/tags",
        PrivateWePurchasePaymentTagList.as_view(),
        name="weapi.purchase-payment-tag-list",
    ),
    path(
        r"/payments/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWePurchasePaymentFileItemDetails.as_view(),
        name="weapi.purchase-payment-file-item-details",
    ),
    path(
        r"/payments/<uuid:uid>/files",
        PrivateWePurchasePaymentFileItemList.as_view(),
        name="weapi.purchase-payment-file-list",
    ),
    path(
        r"/payments/<uuid:uid>/items/<uuid:item_uid>",
        PrivateWePurchasePaymentItemDetails.as_view(),
        name="weapi.purchase-payment-item-details",
    ),
    path(
        r"/payments/<uuid:uid>/items",
        PrivateWePurchasePaymentItemsList.as_view(),
        name="weapi.purchase-payment-item-list",
    ),
    path(
        r"/payments/<uuid:uid>",
        PrivateWePurchasePaymentDetails.as_view(),
        name="weapi.purchase-payment-details",
    ),
    path(
        r"/payments",
        PrivateWePurchasePaymentList.as_view(),
        name="weapi.purchase-payment-list",
    ),
    # Purchase related
    path(
        r"/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWePurchaseFileItemDetails.as_view(),
        name="weapi.purchase-file-item-details",
    ),
    path(
        r"/<uuid:uid>/files",
        PrivateWePurchaseFileItemList.as_view(),
        name="weapi.purchase-file-item-list",
    ),
    path(
        r"/<uuid:uid>/tags",
        PrivateWePurchaseTagList.as_view(),
        name="weapi.purchase-tag-list",
    ),
    path(
        r"/<uuid:uid>/items/<uuid:item_uid>",
        PrivateWePurchaseItemDetails.as_view(),
        name="weapi.purchase-item-details",
    ),
    path(
        r"/<uuid:uid>/items",
        PrivateWePurchaseItemList.as_view(),
        name="weapi.purchase-item-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWePurchaseDetails.as_view(),
        name="weapi.purchase-details",
    ),
    path(r"", PrivateWePurchaseList.as_view(), name="weapi.purchase-list"),
]
