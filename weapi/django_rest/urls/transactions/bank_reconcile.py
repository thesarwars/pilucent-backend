from django.urls import path
from weapi.django_rest.views.transactions.bank_reconcile import (
    PrivateWeBankReconcileListCreateView,
    PrivateWeReconciliationUndoView,
    PrivateWeReconcileTransactionsView,
    PrivateWeReconciliationLineTickView,
    PrivateWeBankReconciliationSummaryView,
)

urlpatterns = [
    # Bank deposit
    path(
        r"",
        PrivateWeBankReconcileListCreateView.as_view(),
        name="weapi.bank_reconcile.list_create",
    ),
    # reconcile summary
    path(
        r"/summary/<uuid:uid>/",
        PrivateWeBankReconciliationSummaryView.as_view(),
        name="weapi.bank_reconcile.summary",
    ),
    # Undo a closed reconciliation (LIFO)
    path(
        r"/<uuid:uid>/undo",
        PrivateWeReconciliationUndoView.as_view(),
        name="weapi.bank_reconcile.undo",
    ),
    # Tick / untick documents without closing the session
    path(
        r"/<uuid:uid>/lines",
        PrivateWeReconciliationLineTickView.as_view(),
        name="weapi.bank_reconcile.lines",
    ),
    # Reconciled transactions
    path(
        r"/complete",
        PrivateWeReconcileTransactionsView.as_view(),
        name="weapi.transaction_match",
    ),
]
