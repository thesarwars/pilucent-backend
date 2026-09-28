from django.urls import path

from ...views.reports.ap_aging_summary import PrivateWeApAgingSummaryReportView

urlpatterns = [
    path(
        r"",
        PrivateWeApAgingSummaryReportView.as_view(),
        name="weapi.reports.ap-aging-summary",
    ),
]
