from django.urls import path

from ...views.reports.inventory_valuation_detail import (
    PrivateWeInventoryValuationDetailReportView,
)

urlpatterns = [
    path(
        r"",
        PrivateWeInventoryValuationDetailReportView.as_view(),
        name="weapi.reports.inventory-valuation-detail",
    ),
]
