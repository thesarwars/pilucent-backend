from django.urls import path

from ...views.reports.ar_aging_summary import PrivateWeArAgingSummaryReportView

urlpatterns = [
    path(
        r"",
        PrivateWeArAgingSummaryReportView.as_view(),
        name="weapi.reports.ar-aging-summary",
    ),
]
