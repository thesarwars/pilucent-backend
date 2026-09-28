"""Total pay -- one row per employee, one column per pay type."""

from payrollio.django_rest.helpers.payroll_total_pay import build_total_pay
from rest_framework.response import Response

from weapi.django_rest.views.payroll.reports.base import PayrollReportView


class PayrollTotalPayReportView(PayrollReportView):
    report_title = "Total pay report"
    pdf_template = "reports/payrolls/payroll_total_pay_temp.html"
    pdf_filename = "payroll_total_pay_report.pdf"
    payroll_fields = ("employee", "employee__user")
    component_fields = ("payroll", "payroll_type", "payroll_category", "current")

    def build_report(self, request, payrolls, context):
        return build_total_pay(payrolls)

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        # The trailing Total row is not an employee.
        return Response({"employee_count": max(len(report["rows"]) - 1, 0)})
