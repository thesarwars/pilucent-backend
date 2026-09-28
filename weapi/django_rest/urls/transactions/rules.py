from django.urls import path, include
from ...views.transactions.rules import (
    TransactionRuleCreateView,
    TransactionRuleListView,
)

urlpatterns = [
    path(
        "", TransactionRuleCreateView.as_view(), name="POST.create-transaction-rule"
    ),  # /api/v1/we/transactions/rules
    path(
        "/list",
        TransactionRuleListView.as_view(),
        name="POST.create-transaction-rule-list",
    ),  # /api/v1/we/transactions/rules
]
