from django.urls import path, include
from ...views.transactions.csv_transactions import (
    UpsertCSVTransactionsView,
    TransactionListView,
    TransactionSummaryView,
    TransactionDataUpdateView,
)

urlpatterns = [
    path(
        "/upsert", UpsertCSVTransactionsView.as_view(), name="POST.csv_transactions"
    ),  # /api/v1/we/transactions/csv/upsert
    path(
        "/list", TransactionListView.as_view(), name="GET.csv_transactions-list"
    ),  # /api/v1/we/transactions/csv/list
    path(
        "/list/summary",
        TransactionSummaryView.as_view(),
        name="GET.csv_transactions-summary",
    ),  # /api/v1/we/transactions/csv/list/summary
    path(
        "/update",
        TransactionDataUpdateView.as_view(),
        name="PATCH.csv_transactions-upsert-update",
    ),  # /api/v1/we/transactions/csv/update/uid
]
