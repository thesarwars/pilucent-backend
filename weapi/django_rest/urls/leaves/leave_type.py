from django.urls import path
from weapi.django_rest.views.leaves.leave_type import PrivateWeLeaveTypeList, PrivateWeLeaveTypeDetails

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeLeaveTypeDetails.as_view(),
        name="weapi.leaves-details",
    ),
    path(
        r"/",
        PrivateWeLeaveTypeList.as_view(),
        name="weapi.leaves-list",
    ),
]