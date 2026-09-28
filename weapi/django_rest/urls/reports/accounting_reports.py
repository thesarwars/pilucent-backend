from django.urls import path

from weapi.django_rest.views.reports.balance_sheet_comparison import (
    BalanceSheetComparisonView,
    BalanceSheetFullView,
)
from weapi.django_rest.views.reports.custom_summary_report import (
    CustomSummaryReportView,
)
from weapi.django_rest.views.reports.income_by_customer import (
    IncomeByCustomerSummaryView,
)
from weapi.django_rest.views.reports.sales_by_customer import (
    SalesByCustomerSummaryView,
)
from weapi.django_rest.views.reports.sales_lines import (
    SalesByCustomerDetailView,
    SalesByProductServiceDetailView,
    SalesByProductServiceSummaryView,
)
from weapi.django_rest.views.reports.profit_loss_pivots import (
    ProfitLossByCustomerView,
    ProfitLossByStoreView,
    ProfitLossComparisonView,
)


urlpatterns = [
    path(
        "/profit-losses/by-customer",
        ProfitLossByCustomerView.as_view(),
        name="weapi.reports.profit-loss-by-customer",
    ),
    path(
        "/profit-losses/by-store",
        ProfitLossByStoreView.as_view(),
        name="weapi.reports.profit-loss-by-store",
    ),
    path(
        "/profit-losses/comparison",
        ProfitLossComparisonView.as_view(),
        name="weapi.reports.profit-loss-comparison",
    ),
    path(
        "/balance-sheet/full",
        BalanceSheetFullView.as_view(),
        name="weapi.reports.balance-sheet-full",
    ),
    path(
        "/balance-sheet/comparison",
        BalanceSheetComparisonView.as_view(),
        name="weapi.reports.balance-sheet-comparison",
    ),
    path(
        "/sales-by-customer-summary",
        SalesByCustomerSummaryView.as_view(),
        name="weapi.reports.sales-by-customer-summary",
    ),
    path(
        "/sales-by-customer-detail",
        SalesByCustomerDetailView.as_view(),
        name="weapi.reports.sales-by-customer-detail",
    ),
    path(
        "/sales-by-product-service-detail",
        SalesByProductServiceDetailView.as_view(),
        name="weapi.reports.sales-by-product-service-detail",
    ),
    path(
        "/sales-by-product-service-summary",
        SalesByProductServiceSummaryView.as_view(),
        name="weapi.reports.sales-by-product-service-summary",
    ),
    path(
        "/income-by-customer-summary",
        IncomeByCustomerSummaryView.as_view(),
        name="weapi.reports.income-by-customer-summary",
    ),
    path(
        "/custom-summary",
        CustomSummaryReportView.as_view(),
        name="weapi.reports.custom-summary",
    ),
]
