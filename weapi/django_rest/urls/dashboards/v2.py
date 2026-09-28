from django.urls import path

from weapi.django_rest.views.dashboards.v2.kpi_summary import (
    PrivateWeDashboardKpiSummaryView,
)
from weapi.django_rest.views.dashboards.v2.invoice_overview import (
    PrivateWeDashboardInvoiceOverviewView,
)
from weapi.django_rest.views.dashboards.v2.bank_balances import (
    PrivateWeDashboardBankBalancesView,
)
from weapi.django_rest.views.dashboards.v2.profit_loss import (
    PrivateWeDashboardProfitLossView,
)
from weapi.django_rest.views.dashboards.v2.income_vs_expense import (
    PrivateWeDashboardIncomeVsExpenseView,
)
from weapi.django_rest.views.dashboards.v2.expense_breakdown import (
    PrivateWeDashboardExpenseBreakdownView,
)
from weapi.django_rest.views.dashboards.v2.mini_expense_cash import (
    PrivateWeDashboardMiniExpenseCashView,
)
from weapi.django_rest.views.dashboards.v2.ar_aging import (
    PrivateWeDashboardArAgingView,
)
from weapi.django_rest.views.dashboards.v2.ap_aging import (
    PrivateWeDashboardApAgingView,
)
from weapi.django_rest.views.dashboards.v2.cash_flow import (
    PrivateWeDashboardCashFlowView,
)
from weapi.django_rest.views.dashboards.v2.cash_runway import (
    PrivateWeDashboardCashRunwayView,
)
from weapi.django_rest.views.dashboards.v2.recent_transactions import (
    PrivateWeDashboardRecentTransactionsView,
)
from weapi.django_rest.views.dashboards.v2.top_customers import (
    PrivateWeDashboardTopCustomersView,
)
from weapi.django_rest.views.dashboards.v2.top_selling_products import (
    PrivateWeDashboardTopSellingProductsView,
)
from weapi.django_rest.views.dashboards.v2.employee_overview import (
    PrivateWeDashboardEmployeeOverviewView,
)
from weapi.django_rest.views.dashboards.v2.leave_requests import (
    PrivateWeDashboardLeaveRequestsView,
)
from weapi.django_rest.views.dashboards.v2.attendance_summary import (
    PrivateWeDashboardAttendanceSummaryView,
)
from weapi.django_rest.views.dashboards.v2.payroll_snapshot import (
    PrivateWeDashboardPayrollSnapshotView,
)
from weapi.django_rest.views.dashboards.v2.tax_center_snapshot import (
    PrivateWeDashboardTaxCenterSnapshotView,
)
from weapi.django_rest.views.dashboards.v2.todays_workforce import (
    PrivateWeDashboardTodaysWorkforceView,
)
from weapi.django_rest.views.dashboards.v2.upcoming_events import (
    PrivateWeDashboardUpcomingEventsView,
)
from weapi.django_rest.views.dashboards.v2.ai_insights import (
    PrivateWeDashboardAiInsightsView,
)
from weapi.django_rest.views.dashboards.v2.approval_center import (
    PrivateWeDashboardApprovalCenterView,
)
from weapi.django_rest.views.dashboards.v2.activity_feed import (
    PrivateWeDashboardActivityFeedView,
)
from weapi.django_rest.views.dashboards.v2.support_tickets import (
    PrivateWeDashboardSupportTicketsView,
)
from weapi.django_rest.views.dashboards.v2.quick_actions import (
    PrivateWeDashboardQuickActionsView,
)

urlpatterns = [
    # Phase 1 - Finance MVP
    path(
        r"/kpi-summary",
        PrivateWeDashboardKpiSummaryView.as_view(),
        name="weapi.dashboard-v2-kpi-summary",
    ),
    path(
        r"/invoice-overview",
        PrivateWeDashboardInvoiceOverviewView.as_view(),
        name="weapi.dashboard-v2-invoice-overview",
    ),
    path(
        r"/bank-balances",
        PrivateWeDashboardBankBalancesView.as_view(),
        name="weapi.dashboard-v2-bank-balances",
    ),
    path(
        r"/profit-loss",
        PrivateWeDashboardProfitLossView.as_view(),
        name="weapi.dashboard-v2-profit-loss",
    ),
    path(
        r"/income-vs-expense",
        PrivateWeDashboardIncomeVsExpenseView.as_view(),
        name="weapi.dashboard-v2-income-vs-expense",
    ),
    path(
        r"/expense-breakdown",
        PrivateWeDashboardExpenseBreakdownView.as_view(),
        name="weapi.dashboard-v2-expense-breakdown",
    ),
    path(
        r"/mini-expense-cash",
        PrivateWeDashboardMiniExpenseCashView.as_view(),
        name="weapi.dashboard-v2-mini-expense-cash",
    ),
    # Phase 2 - AR/AP & cash analytics
    path(
        r"/ar-aging",
        PrivateWeDashboardArAgingView.as_view(),
        name="weapi.dashboard-v2-ar-aging",
    ),
    path(
        r"/ap-aging",
        PrivateWeDashboardApAgingView.as_view(),
        name="weapi.dashboard-v2-ap-aging",
    ),
    path(
        r"/cash-flow",
        PrivateWeDashboardCashFlowView.as_view(),
        name="weapi.dashboard-v2-cash-flow",
    ),
    path(
        r"/cash-runway",
        PrivateWeDashboardCashRunwayView.as_view(),
        name="weapi.dashboard-v2-cash-runway",
    ),
    path(
        r"/recent-transactions",
        PrivateWeDashboardRecentTransactionsView.as_view(),
        name="weapi.dashboard-v2-recent-transactions",
    ),
    path(
        r"/top-customers",
        PrivateWeDashboardTopCustomersView.as_view(),
        name="weapi.dashboard-v2-top-customers",
    ),
    path(
        r"/top-selling-products",
        PrivateWeDashboardTopSellingProductsView.as_view(),
        name="weapi.dashboard-v2-top-selling-products",
    ),
    # Phase 3 - HR / Payroll / Tax
    path(
        r"/employee-overview",
        PrivateWeDashboardEmployeeOverviewView.as_view(),
        name="weapi.dashboard-v2-employee-overview",
    ),
    path(
        r"/leave-requests",
        PrivateWeDashboardLeaveRequestsView.as_view(),
        name="weapi.dashboard-v2-leave-requests",
    ),
    path(
        r"/attendance-summary",
        PrivateWeDashboardAttendanceSummaryView.as_view(),
        name="weapi.dashboard-v2-attendance-summary",
    ),
    path(
        r"/payroll-snapshot",
        PrivateWeDashboardPayrollSnapshotView.as_view(),
        name="weapi.dashboard-v2-payroll-snapshot",
    ),
    path(
        r"/tax-center-snapshot",
        PrivateWeDashboardTaxCenterSnapshotView.as_view(),
        name="weapi.dashboard-v2-tax-center-snapshot",
    ),
    path(
        r"/todays-workforce",
        PrivateWeDashboardTodaysWorkforceView.as_view(),
        name="weapi.dashboard-v2-todays-workforce",
    ),
    path(
        r"/upcoming-events",
        PrivateWeDashboardUpcomingEventsView.as_view(),
        name="weapi.dashboard-v2-upcoming-events",
    ),
    # Phase 4 - Workflow / AI / Productivity
    path(
        r"/ai-insights",
        PrivateWeDashboardAiInsightsView.as_view(),
        name="weapi.dashboard-v2-ai-insights",
    ),
    path(
        r"/approval-center",
        PrivateWeDashboardApprovalCenterView.as_view(),
        name="weapi.dashboard-v2-approval-center",
    ),
    path(
        r"/activity-feed",
        PrivateWeDashboardActivityFeedView.as_view(),
        name="weapi.dashboard-v2-activity-feed",
    ),
    path(
        r"/support-tickets",
        PrivateWeDashboardSupportTicketsView.as_view(),
        name="weapi.dashboard-v2-support-tickets",
    ),
    path(
        r"/quick-actions",
        PrivateWeDashboardQuickActionsView.as_view(),
        name="weapi.dashboard-v2-quick-actions",
    ),
]
