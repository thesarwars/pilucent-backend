from django.urls import path, include

from ...views.reports.payroll_cost_reports import PrivateWePayrollCostReportList

urlpatterns = [
    path(
        r"",
        PrivateWePayrollCostReportList.as_view(),
        name="weapi.payroll-cost-report-list",
    ),
]
