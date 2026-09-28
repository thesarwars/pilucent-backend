"""Sales by customer summary."""

from rest_framework.response import Response

from weapi.django_rest.helpers.reports.sales_by_customer import (
    build_sales_by_customer,
)
from weapi.django_rest.views.reports.accounting_report_base import (
    AccountingReportView,
    format_span,
)


class SalesByCustomerSummaryView(AccountingReportView):
    report_title = "Sales by Customer Summary"
    pdf_template = "reports/sales_by_customer_summary.html"
    pdf_filename = "sales_by_customer_summary.pdf"

    def build_report(self, request, company):
        date_from, date_to = self.resolve_range(request)
        return {
            "subtitle": format_span(date_from, date_to),
            "date_from": date_from,
            "date_to": date_to,
            # The reference footer names the basis; every figure here comes from
            # the journal as posted, which is accrual.
            "basis": "Accrual Basis",
            **build_sales_by_customer(company, date_from, date_to),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        total = next((r for r in report["rows"] if r["key"] == "total"), None)
        return Response({"total": total["total"] if total else "0.00"})
