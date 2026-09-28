from django.urls import path

from ...views.reports.taxable_sales_summary import (
    PrivateWeTaxableSalesSummaryReportView,
)

urlpatterns = [
    path(
        r"",
        PrivateWeTaxableSalesSummaryReportView.as_view(),
        name="weapi.reports.taxable-sales-summary",
    ),
]
