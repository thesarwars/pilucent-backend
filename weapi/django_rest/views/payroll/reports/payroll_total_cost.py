"""Total payroll cost -- pay plus contributions plus employer taxes."""

from payrollio.django_rest.helpers.payroll_report_common import (
    resolve_pretax_deduction_names,
)
from payrollio.django_rest.helpers.payroll_total_cost import (
    build_total_payroll_cost,
)
from rest_framework.response import Response

from weapi.django_rest.views.payroll.reports.base import PayrollReportView


class PayrollTotalCostReportView(PayrollReportView):
    report_title = "Total payroll cost report"
    pdf_template = "reports/payrolls/payroll_total_cost_temp.html"
    pdf_filename = "payroll_total_cost_report.pdf"
    # The reference subtitle reads "From … from all locations" -- this report
    # never names an employee.
    subtitle_names_employees = False

    def build_report(self, request, payrolls, context):
        company = context["company"]
        return build_total_payroll_cost(
            payrolls, pretax_names=resolve_pretax_deduction_names(company)
        )

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        total = next(
            (row for row in report["rows"] if row["kind"] == "total"), None
        )
        return Response({"total_payroll_cost": total["amount"] if total else "0.00"})
