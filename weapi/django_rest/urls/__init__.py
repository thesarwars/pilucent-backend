from django.urls import path, include

urlpatterns = [
    path("", include("weapi.django_rest.urls.we")),

    path("/addresses", include("weapi.django_rest.urls.addresses")),

    path("/agencies", include("weapi.django_rest.urls.agencies")),
    path("/attendances", include("weapi.django_rest.urls.attendances")),
    path("/attachments", include("weapi.django_rest.urls.attachments")),
    path("/audit-logs", include("weapi.django_rest.urls.audit_logs")),

    path("/brands", include("weapi.django_rest.urls.brands")),

    path("/categories", include("weapi.django_rest.urls.categories")),
    path("/chart-of-accounts", include("weapi.django_rest.urls.chart_of_accounts")),
    path("/companies", include("weapi.django_rest.urls.companies")),
    path("/credit-notes", include("weapi.django_rest.urls.creditnotes")),
    path("/customers", include("weapi.django_rest.urls.customers")),
    path("/currencies", include("weapi.django_rest.urls.currencies")),

    path("/daily-time-trackings", include("weapi.django_rest.urls.time_trackings")),
    path("/dashboards", include("weapi.django_rest.urls.dashboards")),

    path("/expenses", include("weapi.django_rest.urls.expenses")),
    path("/employees", include("weapi.django_rest.urls.employees")),

    path("/journals", include("weapi.django_rest.urls.journals")),

    path("/pay-bills", include("weapi.django_rest.urls.pay_bills")),
    path("/payment-methods", include("weapi.django_rest.urls.payment_methods")),
    path("/products", include("weapi.django_rest.urls.products")),
    path("/purchases", include("weapi.django_rest.urls.purchases")),

    path("/recurring-templates", include("weapi.django_rest.urls.recurring_transactions")),

    path("/nexus", include("weapi.django_rest.urls.nexus")),

    path("/reports", include("weapi.django_rest.urls.reports")),

    path("/salary-adjustments", include("weapi.django_rest.urls.salary_adjustment")),
    path("/sales/reports", include("weapi.django_rest.urls.sale_reports")),
    path("/sales", include("weapi.django_rest.urls.sales")),
    path("/suppliers", include("weapi.django_rest.urls.suppliers")),
    path("/support-tickets", include("weapi.django_rest.urls.support_and_tickets")),
    path("/subscriptions", include("weapi.django_rest.urls.subscriptions")),
    path("/stock", include("weapi.django_rest.urls.stock")),

    path("/terms", include("weapi.django_rest.urls.terms")),
    path("/transactions", include("weapi.django_rest.urls.transactions")),
    path("/payroll", include("weapi.django_rest.urls.payroll")),

    path("/warehouses", include("weapi.django_rest.urls.warehouses")),
	
    path("/leaves", include("weapi.django_rest.urls.leaves")),
	path("/pdf", include("weapi.django_rest.urls.pdf")),
    path("/holidays", include("weapi.django_rest.urls.holidays")),
    path("/moov-money", include("weapi.django_rest.urls.moov_money")),
    path("/taxbandits", include("weapi.django_rest.urls.taxbandits")),
    path("/receipt-ocr", include("weapi.django_rest.urls.receipt_ocr")),

    path("/data-migrations", include("datamigrationio.django_rest.urls")),
]
