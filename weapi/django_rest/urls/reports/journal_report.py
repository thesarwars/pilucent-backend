from django.urls import path
from weapi.django_rest.views.reports.journal_report import (
    PrivateWeJournalReportList,
    PrivateWeJournalEntriesReport,
)

urlpatterns = [
    path("", PrivateWeJournalReportList.as_view(), name="weapi.reports.journal-report"),
    path(
        "/entries",
        PrivateWeJournalEntriesReport.as_view(),
        name="weapi.reports.journal-entries-report",
    ),
]
