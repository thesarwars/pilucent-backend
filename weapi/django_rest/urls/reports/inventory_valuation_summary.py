from django.urls import path

from ...views.reports.inventory_valuation_summary import (
    PrivateWeInventoryValuationSummaryReportView,
)

urlpatterns = [
    path(
        r"",
        PrivateWeInventoryValuationSummaryReportView.as_view(),
        name="weapi.reports.inventory-valuation-summary",
    ),
]
