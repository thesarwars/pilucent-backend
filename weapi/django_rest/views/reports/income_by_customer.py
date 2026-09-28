"""Income by customer summary."""

from rest_framework.response import Response

from weapi.django_rest.helpers.reports.income_by_customer import (
    build_income_by_customer,
)
from weapi.django_rest.views.reports.accounting_report_base import (
    AccountingReportView,
    format_span,
)


class IncomeByCustomerSummaryView(AccountingReportView):
    report_title = "Income by Customer Summary"
    pdf_template = "reports/income_by_customer_summary.html"
    pdf_filename = "income_by_customer_summary.pdf"

    def build_report(self, request, company):
        date_from, date_to = self.resolve_range(request)
        return {
            "subtitle": format_span(date_from, date_to),
            "date_from": date_from,
            "date_to": date_to,
            # Every figure comes from the journal as posted, which is accrual.
            "basis": "Accrual Basis",
            **build_income_by_customer(company, date_from, date_to),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        total = next((r for r in report["rows"] if r["key"] == "total"), None)
        return Response(
            {
                "income": total["income"] if total else "0.00",
                "expenses": total["expenses"] if total else "0.00",
                "net_income": total["net_income"] if total else "0.00",
            }
        )
