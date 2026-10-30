from django.urls import path

from ..views import bd_payrun as v

# Run payroll (docs/backend/run-payroll-done.md §6).
urlpatterns = [
    path(r"", v.PrRuns.as_view(), name="weapi.bd-payrun-runs"),
    path(r"/overview", v.PrOverview.as_view(), name="weapi.bd-payrun-overview"),
    path(r"/profiles", v.PrProfiles.as_view(), name="weapi.bd-payrun-profiles"),
    path(r"/<uuid:uid>", v.PrRun.as_view(), name="weapi.bd-payrun-run"),
    path(r"/<uuid:uid>/lines/<uuid:line>", v.PrLine.as_view(), name="weapi.bd-payrun-line"),
    path(r"/<uuid:uid>/lines/<uuid:line>/mark-failed", v.PrMarkFailed.as_view(), name="weapi.bd-payrun-mark-failed"),
    path(r"/<uuid:uid>/include-all", v.PrIncludeAll.as_view(), name="weapi.bd-payrun-include-all"),
    path(r"/<uuid:uid>/compute", v.PrCompute.as_view(), name="weapi.bd-payrun-compute"),
    path(r"/<uuid:uid>/exceptions/<uuid:exc>/resolve", v.PrException.as_view(), name="weapi.bd-payrun-resolve"),
    path(r"/<uuid:uid>/approve", v.PrApprove.as_view(), name="weapi.bd-payrun-approve"),
    path(r"/<uuid:uid>/cancel", v.PrCancel.as_view(), name="weapi.bd-payrun-cancel"),
    path(r"/<uuid:uid>/payment-instructions", v.PrInstruct.as_view(), name="weapi.bd-payrun-instruct"),
    path(r"/<uuid:uid>/payment-instructions/<uuid:ins>/file", v.PrInstructionFile.as_view(),
         name="weapi.bd-payrun-file"),
    path(r"/<uuid:uid>/mark-paid", v.PrMarkPaid.as_view(), name="weapi.bd-payrun-mark-paid"),
    path(r"/<uuid:uid>/release", v.PrRelease.as_view(), name="weapi.bd-payrun-release"),
    path(r"/<uuid:uid>/register", v.PrRegister.as_view(), name="weapi.bd-payrun-register"),
]
