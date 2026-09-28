from django.urls import path
from weapi.django_rest.views.reports.cash_flow import (
    PrivateWeCashFlowReportList,
)

urlpatterns = [
    path("", PrivateWeCashFlowReportList.as_view(), name="weapi.reports.cash-flow-report"),
]
