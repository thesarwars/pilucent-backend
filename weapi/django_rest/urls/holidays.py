from django.urls import path

from ..views.holidays import (
    PrivateWeHolidayListCreateView,
    PrivateWeHolidayDetailView,
    PrivateWeHolidayDetailsListCreateView,
    PrivateWeHolidayDetailsDetailView,
)

urlpatterns = [
    path(
        r"/<uuid:uid>/details/<uuid:detail_uid>",
        PrivateWeHolidayDetailsDetailView.as_view(),
        name="weapi.holiday-detail-details",
    ),
    path(
        r"/<uuid:uid>/details",
        PrivateWeHolidayDetailsListCreateView.as_view(),
        name="weapi.holiday-details-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeHolidayDetailView.as_view(),
        name="weapi.holiday-details",
    ),
    path(r"", PrivateWeHolidayListCreateView.as_view(), name="weapi.holiday-list"),
]
