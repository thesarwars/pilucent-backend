from django.urls import path

from weapi.django_rest.views.attachments import (
    PrivateWeAttachmentList,
    PrivateWeAttachmentDetails,
)

urlpatterns = [
    path(
        r"",
        PrivateWeAttachmentList.as_view(),
        name="weapi.attachments-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeAttachmentDetails.as_view(),
        name="weapi.attachments-details",
    ),
]
