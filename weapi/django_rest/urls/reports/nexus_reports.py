from django.urls import path

from ...views.reports.nexus_reports import (
    PrivateWeNexusApproachingRiskReportView,
    PrivateWeNexusExposureReportView,
    PrivateWeNexusThresholdHistoryReportView,
)

urlpatterns = [
    path(
        r"/exposure",
        PrivateWeNexusExposureReportView.as_view(),
        name="weapi.reports.nexus-exposure",
    ),
    path(
        r"/approaching-risk",
        PrivateWeNexusApproachingRiskReportView.as_view(),
        name="weapi.reports.nexus-approaching-risk",
    ),
    path(
        r"/threshold-history",
        PrivateWeNexusThresholdHistoryReportView.as_view(),
        name="weapi.reports.nexus-threshold-history",
    ),
]
