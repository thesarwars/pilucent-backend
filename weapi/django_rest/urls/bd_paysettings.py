from django.urls import path

from ..views import bd_paysettings as v

# Payroll settings (docs/backend/payroll-settings-done.md §6).
urlpatterns = [
    path(r"/summary", v.PsSummary.as_view(), name="weapi.bd-payset-summary"),
    path(r"/elections", v.PsElections.as_view(), name="weapi.bd-payset-elections"),
    path(r"/elections/<str:key>", v.PsElection.as_view(), name="weapi.bd-payset-election"),
    path(r"/elections/<str:key>/preview", v.PsElectionPreview.as_view(), name="weapi.bd-payset-election-preview"),
    path(r"/proposals/<uuid:uid>/<str:action>", v.PsProposal.as_view(), name="weapi.bd-payset-proposal"),
    path(r"/schedule", v.PsSchedule.as_view(), name="weapi.bd-payset-schedule"),
    path(r"/schedule/check", v.PsScheduleCheck.as_view(), name="weapi.bd-payset-schedule-check"),
    path(r"/schemes", v.PsSchemes.as_view(), name="weapi.bd-payset-schemes"),
    path(r"/schemes/accounts", v.PsSchemeAccounts.as_view(), name="weapi.bd-payset-scheme-accounts"),
    path(r"/schemes/PF/auto-enrol", v.PsAutoEnrol.as_view(), name="weapi.bd-payset-auto-enrol"),
    path(r"/schemes/<str:code>", v.PsScheme.as_view(), name="weapi.bd-payset-scheme"),
    path(r"/schemes/<str:code>/gl", v.PsSchemeGl.as_view(), name="weapi.bd-payset-scheme-gl"),
    path(r"/schemes/<str:code>/participants", v.PsParticipants.as_view(), name="weapi.bd-payset-participants"),
    path(r"/gl-accounts", v.PsGlAccounts.as_view(), name="weapi.bd-payset-gl-accounts"),
    path(r"/readiness", v.PsReadiness.as_view(), name="weapi.bd-payset-readiness"),
    path(r"/changelog", v.PsChangelog.as_view(), name="weapi.bd-payset-changelog"),
]
