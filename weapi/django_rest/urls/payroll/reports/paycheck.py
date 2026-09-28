from django.urls import path

from weapi.django_rest.views.payroll.reports.paycheck import (
    PaycheckReportDetailView,
    PaycheckReportListView,
)

urlpatterns = [
    path(
        "/paycheck",
        PaycheckReportListView.as_view(),
        name="weapi.payroll.reports.paycheck",
    ), # /api/v1/payroll/reports/paycheck/
    path(
        "/paycheck/detail",
        PaycheckReportDetailView.as_view(),
        name="weapi.payroll.reports.paycheck-detail",
    ),
]
