from django.urls import path

from ..views.creditnotes import (
    PrivateWeCreditNoteList,
    PrivateWeCreditNoteDetails,
    PrivateWeCreditNoteItemsList,
    PrivateWeCreditNoteItemsDetails,
    PrivateWeCreditNoteTagsList,
    PrivateWeCreditNoteFileItemList,
    PrivateWeCreditNoteFileItemDetails,
)

urlpatterns = [
    path(
        r"/<uuid:uid>/files/<uuid:file_uid>",
        PrivateWeCreditNoteFileItemDetails.as_view(),
        name="weapi.creditnote-file-details",
    ),
    path(
        r"/<uuid:uid>/files",
        PrivateWeCreditNoteFileItemList.as_view(),
        name="weapi.creditnote-file-item-list",
    ),
    path(
        r"/<uuid:uid>/tags",
        PrivateWeCreditNoteTagsList.as_view(),
        name="weapi.creditnote-tag-list",
    ),
    path(
        r"/<uuid:uid>/items/<uuid:item_uid>",
        PrivateWeCreditNoteItemsDetails.as_view(),
        name="weapi.creditnote-item-details",
    ),
    path(
        r"/<uuid:uid>/items",
        PrivateWeCreditNoteItemsList.as_view(),
        name="weapi.creditnote-item-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeCreditNoteDetails.as_view(),
        name="weapi.creditnote-details",
    ),
    path(r"", PrivateWeCreditNoteList.as_view(), name="weapi.creditnote-list"),
]
