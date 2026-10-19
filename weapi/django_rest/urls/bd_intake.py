from django.urls import path

from ..views import bd_intake as v

# Attendance intake (docs/backend/attendance-intake-done.md §7), beside the
# register's /attendance routes.
urlpatterns = [
    path(r"/summary", v.IntakeSummary.as_view(), name="weapi.bd-intake-summary"),
    path(r"/sample", v.IntakeSample.as_view(), name="weapi.bd-intake-sample"),
    path(r"/profiles", v.IntakeProfiles.as_view(), name="weapi.bd-intake-profiles"),
    path(r"/profiles/test", v.IntakeProfileTest.as_view(), name="weapi.bd-intake-profile-test"),
    path(r"/profiles/<uuid:uid>", v.IntakeProfile.as_view(), name="weapi.bd-intake-profile"),
    path(r"/batches", v.IntakeBatches.as_view(), name="weapi.bd-intake-batches"),
    path(r"/batches/<uuid:uid>", v.IntakeBatch.as_view(), name="weapi.bd-intake-batch"),
    path(r"/batches/<uuid:uid>/raw", v.IntakeBatchRaw.as_view(), name="weapi.bd-intake-batch-raw"),
    path(r"/batches/<uuid:uid>/<str:action>", v.IntakeBatchAction.as_view(), name="weapi.bd-intake-batch-action"),
    path(r"/device-ids", v.IntakeDeviceIds.as_view(), name="weapi.bd-intake-device-ids"),
    path(r"/device-maps", v.IntakeDeviceMaps.as_view(), name="weapi.bd-intake-device-maps"),
    path(r"/device-maps/<uuid:uid>/close", v.IntakeDeviceMapClose.as_view(), name="weapi.bd-intake-device-map-close"),
    path(r"/periods", v.IntakePeriods.as_view(), name="weapi.bd-intake-periods"),
    path(r"/periods/<str:month>/<str:action>", v.IntakePeriodAction.as_view(), name="weapi.bd-intake-period-action"),
]
