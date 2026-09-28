from django.urls import path

from ..views.pay_bills import (
    PrivateWePayBillList,
    PrivateWePayBillDetails,
    PrivateWePayBillItemList,
    PrivateWePayBillItemDetails,
    PrivateWePayBillFileItemList,
    PrivateWePayBillFileItemDetails,
    PrivateWePaybillTagList
)


urlpatterns = [
    # Tag related
    path(
        r"/<uuid:uid>/tags",
        PrivateWePaybillTagList.as_view(),
        name="weapi.pay-bill-tag-list",
    ),
    # File related
    path(
        r"/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWePayBillFileItemDetails.as_view(),
        name="weapi.pay-bill-file-item-details",
    ),
    path(
        r"/<uuid:uid>/files",
        PrivateWePayBillFileItemList.as_view(),
        name="weapi.pay-bill-file-item-list",
    ),
    # Item related
    path(
        r"/<uuid:uid>/items/<uuid:item_uid>",
        PrivateWePayBillItemDetails.as_view(),
        name="weapi.pay-bill-item-details",
    ),
    path(
        r"/<uuid:uid>/items",
        PrivateWePayBillItemList.as_view(),
        name="weapi.pay-bill-item-list",
    ),
    path(
        r"/<uuid:uid>", PrivateWePayBillDetails.as_view(), name="weapi.pay-bill-details"
    ),
    path(r"", PrivateWePayBillList.as_view(), name="weapi.pay-bill-list"),
]
