from django.urls import path, include

from ...views.reports.transaction_reports import (
    PrivateWeTrialBalanceList,
    PrivateWeTransactionList,
)

urlpatterns = [
    path(
        r"/trial-balances",
        PrivateWeTrialBalanceList.as_view(),
        name="weapi.trila-balance-list",
    ),
    path(
        r"",
        PrivateWeTransactionList.as_view(),
        name="weapi.report-transaction-list",
    ),
]
