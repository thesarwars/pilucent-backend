from django.urls import path, include

from ...views.reports.cash_flow import PrivateWeCashFlowReportList

urlpatterns = [
    path(r"", PrivateWeCashFlowReportList.as_view(), name="weapi.report.sales-tax"),
]
