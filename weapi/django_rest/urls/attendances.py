from django.urls import path

from ..views.attendances import (
    PrivateWeAttendanceList,
    PrivateWeAttendanceDetails,
    PrivateWeAttendanceProcessList,
    PrivateWePunchDataDailyTimeListCreate,
    PrivateWeBulkAttendancePreview,
    PrivateWeBulkAttendanceCommit,
)

urlpatterns = [
    path(
        r"/bulk/preview",
        PrivateWeBulkAttendancePreview.as_view(),
        name="weapi.attendance-bulk-preview",
    ),
    path(
        r"/bulk/commit",
        PrivateWeBulkAttendanceCommit.as_view(),
        name="weapi.attendance-bulk-commit",
    ),
    path(
        r"/punch-data",
        PrivateWePunchDataDailyTimeListCreate.as_view(),
        name="weapi.punch-data-daily-time-list-create",
    ),
    path(
        r"/processes",
        PrivateWeAttendanceProcessList.as_view(),
        name="weapi.attendance-processes-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeAttendanceDetails.as_view(),
        name="weapi.attendance-details",
    ),
    path(
        r"",
        PrivateWeAttendanceList.as_view(),
        name="weapi.attendance-list",
    ),
]
