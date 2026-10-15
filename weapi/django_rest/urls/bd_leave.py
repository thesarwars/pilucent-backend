from django.urls import path

from ..views import bd_leave as v

# Leave (docs/backend/leave-backend.md §7). Singular, beside the original
# product's /leaves routes.
urlpatterns = [
    path(r"/summary", v.LeaveSummary.as_view(), name="weapi.bd-leave-summary"),
    path(r"/types", v.LeaveTypes.as_view(), name="weapi.bd-leave-types"),
    path(r"/policy", v.LeavePolicy.as_view(), name="weapi.bd-leave-policy"),
    path(r"/balances", v.LeaveBalances.as_view(), name="weapi.bd-leave-balances"),
    path(r"/requests", v.LeaveApplications.as_view(), name="weapi.bd-leave-requests"),
    path(r"/requests/preview", v.LeavePreview.as_view(), name="weapi.bd-leave-request-preview"),
    path(r"/requests/<str:reference>/<str:action>", v.LeaveRequestAction.as_view(),
         name="weapi.bd-leave-request-action"),
    path(r"/approvals", v.LeaveApprovals.as_view(), name="weapi.bd-leave-approvals"),
    path(r"/away", v.LeaveAway.as_view(), name="weapi.bd-leave-away"),
    path(r"/employees/<str:code>", v.LeaveEmployee.as_view(), name="weapi.bd-leave-employee"),
    path(r"/employees/<str:code>/encashment", v.LeaveEncashmentPreview.as_view(),
         name="weapi.bd-leave-encashment-preview"),
    path(r"/grants", v.LeaveGrants.as_view(), name="weapi.bd-leave-grants"),
    path(r"/grants/bulk", v.LeaveBulkGrants.as_view(), name="weapi.bd-leave-grants-bulk"),
    path(r"/ledger/<uuid:uid>/reverse", v.LeaveReverse.as_view(), name="weapi.bd-leave-reverse"),
    path(r"/accrual-runs", v.LeaveAccrualRun.as_view(), name="weapi.bd-leave-accrual-runs"),
    path(r"/year-end-close", v.LeaveYearEnd.as_view(), name="weapi.bd-leave-year-end"),
    path(r"/encashments", v.LeaveEncashments.as_view(), name="weapi.bd-leave-encashments"),
    path(r"/encashments/<str:reference>/<str:action>", v.LeaveEncashmentAction.as_view(),
         name="weapi.bd-leave-encashment-action"),
    path(r"/maternity", v.LeaveMaternity.as_view(), name="weapi.bd-leave-maternity"),
    path(r"/maternity/<str:reference>/delivery", v.LeaveMaternityDelivery.as_view(),
         name="weapi.bd-leave-maternity-delivery"),
    path(r"/maternity/<str:reference>/restricted", v.LeaveMaternityRestricted.as_view(),
         name="weapi.bd-leave-maternity-restricted"),
]
