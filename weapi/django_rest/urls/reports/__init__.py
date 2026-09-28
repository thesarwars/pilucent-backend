from django.urls import path, include

urlpatterns = [
    # These sit above the single-report includes below because the existing
    # "/profit-losses" and "/balance-sheet" includes register a catch-all
    # r"" route that would otherwise swallow their sub-paths.
    path("", include("weapi.django_rest.urls.reports.accounting_reports")),
    path(
        "/payroll-cost-reports",
        include("weapi.django_rest.urls.reports.payroll_cost_reports"),
    ),
    path("/balance-sheet", include("weapi.django_rest.urls.reports.balance_sheet")),
    path("/journal-report", include("weapi.django_rest.urls.reports.journal_report")),
    path(
        "/transactions", include("weapi.django_rest.urls.reports.transaction_reports")
    ),
    path("/cash-flow", include("weapi.django_rest.urls.reports.cash_flow")),
    path(
        "/profit-losses", include("weapi.django_rest.urls.reports.profit_loss_reports")
    ),
    path("/general-ledgers", include("weapi.django_rest.urls.reports.general_ledgers")),
    path("/sales-tax", include("weapi.django_rest.urls.reports.sales_tax_report")),
    path("/customers", include("weapi.django_rest.urls.reports.customer_reports")),
    path(
        "/ap-aging-detail",
        include("weapi.django_rest.urls.reports.ap_aging_detail"),
    ),
    path(
        "/ap-aging-summary",
        include("weapi.django_rest.urls.reports.ap_aging_summary"),
    ),
    path(
        "/ar-aging-detail",
        include("weapi.django_rest.urls.reports.ar_aging_detail"),
    ),
    path(
        "/ar-aging-summary",
        include("weapi.django_rest.urls.reports.ar_aging_summary"),
    ),
    path(
        "/inventory-valuation-summary",
        include("weapi.django_rest.urls.reports.inventory_valuation_summary"),
    ),
    path(
        "/inventory-valuation-detail",
        include("weapi.django_rest.urls.reports.inventory_valuation_detail"),
    ),
    path(
        "/nexus",
        include("weapi.django_rest.urls.reports.nexus_reports"),
    ),
    path(
        "/taxable-sales-summary",
        include("weapi.django_rest.urls.reports.taxable_sales_summary"),
    ),
    path(
        "/sales-tax-liability",
        include("weapi.django_rest.urls.reports.sales_tax_liability"),
    ),
]
