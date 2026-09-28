from django.urls import path

from weapi.django_rest.views.leaves.leave_encashment import (
    PrivateWeLeaveEncashmentList,
    PrivateWeLeaveEncashmentDetails,
    PrivateWeLeaveEncashmentItemListCreateView,
    PrivateWeLeaveEncashmentItemDetailView,
)

urlpatterns = [
    path(
        r"/items/",
        PrivateWeLeaveEncashmentItemListCreateView.as_view(),
        name="weapi.leave-encashment-item-list-create",
    ),
    path(
        r"/items/<uuid:uid>/",
        PrivateWeLeaveEncashmentItemDetailView.as_view(),
        name="weapi.leave-encashment-item-detail",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeLeaveEncashmentDetails.as_view(),
        name="weapi.leave-encashment-details",
    ),
    path(
        r"/",
        PrivateWeLeaveEncashmentList.as_view(),
        name="weapi.leave-encashment-list",
    ),
]
