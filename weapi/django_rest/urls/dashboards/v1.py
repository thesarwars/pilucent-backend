from django.urls import path

from weapi.django_rest.views.dashboards.v1.dashboards import (
    PrivateWeDashboardProfitLossOverview,
    PrivateWeDashboardBankOverview,
    PrivateWeDashboardExpenseOverview,
    PrivateWeDashboardFinanceOverview,
)

urlpatterns = [
    path(
        r"/finance-overview",
        PrivateWeDashboardFinanceOverview.as_view(),
        name="weapi.dashboard-finance-overview",
    ),
    path(
        r"/expense-overview",
        PrivateWeDashboardExpenseOverview.as_view(),
        name="weapi.dashboard-expense-overview",
    ),
    path(
        r"/bank-overview",
        PrivateWeDashboardBankOverview.as_view(),
        name="weapi.dashboard-bank-overview",
    ),
    path(
        r"/profit-losses-overview",
        PrivateWeDashboardProfitLossOverview.as_view(),
        name="weapi.dashboard-profit-loss-overview",
    ),
]
