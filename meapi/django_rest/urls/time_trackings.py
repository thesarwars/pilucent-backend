from django.urls import path

from ..views.attendances import (
    PrivateMeDailyTimeTrackingList,
    PrivateMeDailyTimeTrackingDetails,
    PrivateMeDailyTimeTrackingSessionList,
    PrivateMeDailyTimeTrackingSessionDetails,
)

urlpatterns = [
    # Attendance session
    path(
        r"/<uuid:uid>/sessions/<uuid:session_uid>",
        PrivateMeDailyTimeTrackingSessionDetails.as_view(),
        name="meapi.daily-time-tracking-session-details",
    ),
    path(
        r"/<uuid:uid>/sessions",
        PrivateMeDailyTimeTrackingSessionList.as_view(),
        name="meapi.daily-time-trcking-session-list",
    ),
    # Attendance
    path(
        r"/<uuid:uid>",
        PrivateMeDailyTimeTrackingDetails.as_view(),
        name="meapi.daily-time-tracking-details",
    ),
    path(
        r"",
        PrivateMeDailyTimeTrackingList.as_view(),
        name="meapi.daily-time-tracking-list",
    ),
]
