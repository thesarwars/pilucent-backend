from django.urls import path
from weapi.django_rest.views.reports.balance_sheet import (
    BalanceSheetDetailsView,
    PrivateWeBalanceSheetSummaryView,
    PrivateWeBalanceSheetSummaryList,
    PrivateWeBalanceSheetView,
)

urlpatterns = [
    path(
        r"/details",
        BalanceSheetDetailsView.as_view(),
        name="weapi.reports.balance-sheet-details",
    ),
    path(
        r"/summary",
        PrivateWeBalanceSheetSummaryView.as_view(),
        name="weapi.reports.balance-sheet-summary",
    ),
    path(
        r"/summary-list",
        PrivateWeBalanceSheetSummaryList.as_view(),
        name="weapi.reports.balance-sheet-summary-list",
    ),
    path(
        r"",
        PrivateWeBalanceSheetView.as_view(),
        name="weapi.reports.balance-sheet-list",
    ),
]
