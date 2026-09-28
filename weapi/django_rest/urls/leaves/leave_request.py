from django.urls import path
from weapi.django_rest.views.leaves.leave_request import (
    PrivateWeLeaveRequestList,
    PrivateWeLeaveRequestDetails,
    PrivateWeLeaveRequestStatusUpdate,
)

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeLeaveRequestDetails.as_view(),
        name="weapi.leaves-details",
    ),
    path(
        r"/",
        PrivateWeLeaveRequestList.as_view(),
        name="weapi.leaves-list",
    ),
    path(
        r"/<uuid:uid>/status/",
        PrivateWeLeaveRequestStatusUpdate.as_view(),
        name="weapi.leaves-status-update",
    ),
]
