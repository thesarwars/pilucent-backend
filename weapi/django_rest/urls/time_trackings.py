from django.urls import path

from ..views.time_trackings import (
    PrivateWeDailyTimeTrackingList,
    PrivateWeDailyTimeTrackingDetails
)

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeDailyTimeTrackingDetails.as_view(),
        name="weapi.daily-time-tracking-details",
    ),
    path(
        r"",
        PrivateWeDailyTimeTrackingList.as_view(),
        name="weapi.daily-time-tracking-list",
    ),
]
