from django.urls import path

from ...views.reports.ap_aging_detail import PrivateWeApAgingDetailReportView

urlpatterns = [
    path(
        r"",
        PrivateWeApAgingDetailReportView.as_view(),
        name="weapi.reports.ap-aging-detail",
    ),
]
