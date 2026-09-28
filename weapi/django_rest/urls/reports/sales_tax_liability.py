from django.urls import path

from ...views.reports.sales_tax_liability import (
    PrivateWeSalesTaxLiabilityReportView,
)

urlpatterns = [
    path(
        r"",
        PrivateWeSalesTaxLiabilityReportView.as_view(),
        name="weapi.reports.sales-tax-liability",
    ),
]
