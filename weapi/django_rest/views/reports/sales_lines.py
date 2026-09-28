"""Sales by Customer Detail / Sales by Product-Service Detail / Summary.

Three groupings of the same transaction lines -- the builders share one
collector, so the two details and the summary can never disagree on which
lines count.
"""

from rest_framework.response import Response

from weapi.django_rest.helpers.reports.sales_lines import (
    build_sales_by_product_summary,
    build_sales_detail,
)
from weapi.django_rest.views.reports.accounting_report_base import (
    AccountingReportView,
    format_span,
)


class _SalesLinesReportView(AccountingReportView):
    def report_payload(self, company, date_from, date_to):
        raise NotImplementedError

    def build_report(self, request, company):
        date_from, date_to = self.resolve_range(request)
        return {
            "subtitle": format_span(date_from, date_to),
            "date_from": date_from,
            "date_to": date_to,
            # Lines count by transaction date, as posted -- accrual.
            "basis": "Accrual Basis",
            **self.report_payload(company, date_from, date_to),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        total = next((r for r in report["rows"] if r["key"] == "total"), None)
        return Response(
            {
                "quantity": total["quantity"] if total else "0.00",
                "total": total["amount"] if total else "0.00",
            }
        )


class SalesByCustomerDetailView(_SalesLinesReportView):
    report_title = "Sales by Customer Detail"
    pdf_template = "reports/sales_lines_detail.html"
    pdf_filename = "sales_by_customer_detail.pdf"

    def report_payload(self, company, date_from, date_to):
        return build_sales_detail(company, date_from, date_to, group_by="customer")


class SalesByProductServiceDetailView(_SalesLinesReportView):
    report_title = "Sales by Product/Service Detail"
    pdf_template = "reports/sales_lines_detail.html"
    pdf_filename = "sales_by_product_service_detail.pdf"

    def report_payload(self, company, date_from, date_to):
        return build_sales_detail(company, date_from, date_to, group_by="product")


class SalesByProductServiceSummaryView(_SalesLinesReportView):
    report_title = "Sales by Product/Service Summary"
    pdf_template = "reports/sales_by_product_service_summary.html"
    pdf_filename = "sales_by_product_service_summary.pdf"

    def report_payload(self, company, date_from, date_to):
        return build_sales_by_product_summary(company, date_from, date_to)
