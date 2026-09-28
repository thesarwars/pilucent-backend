from django.urls import path

from ...views.reports.ar_aging_detail import PrivateWeArAgingDetailReportView

urlpatterns = [
    path(
        r"",
        PrivateWeArAgingDetailReportView.as_view(),
        name="weapi.reports.ar-aging-detail",
    ),
]
