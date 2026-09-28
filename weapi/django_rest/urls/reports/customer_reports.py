from django.urls import path
from ...views.reports.customer_reports import (
    PrivateWeCustomerBalanceSheetSummaryReportView,
)

urlpatterns = [
    path(
        r"/balance-sheet-summary-details",
        PrivateWeCustomerBalanceSheetSummaryReportView.as_view(),
        name="weapi.reports.customer-balance-sheet",
    ),
]
