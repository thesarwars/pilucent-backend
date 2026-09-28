"""Time off -- current balances for active employees.

A snapshot rather than a period, so like the employee details report it reads
`Employee` and takes no date range.
"""

from collections import defaultdict

from employeeio.models import Employee
from leaveio.models import EmployeeLeaveAllocation
from payrollio.django_rest.helpers.time_off import build_time_off
from rest_framework import status
from rest_framework.response import Response

from weapi.django_rest.views.payroll.reports.base import PayrollReportView


class TimeOffReportView(PayrollReportView):
    report_title = "Time off"
    pdf_template = "reports/payrolls/time_off_temp.html"
    pdf_filename = "time_off_report.pdf"
    filterset_class = None  # The sibling filterset targets PayrollSalaryProcess.
    filter_backends = []

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            Employee.objects.select_related("user")
            # "for active employees" is part of the report's own title, not a
            # filter the caller chose, so it is applied here rather than left
            # to a query parameter.
            .filter(user__companyuser__company=user_company, status="ACTIVE")
            .distinct()
        )

    def _allocations(self, employees):
        """Every allocation for every employee, in one query."""
        by_employee = defaultdict(list)
        employee_ids = [employee.id for employee in employees]
        if not employee_ids:
            return by_employee
        for allocation in EmployeeLeaveAllocation.objects.filter(
            employee_id__in=employee_ids
        ).select_related("leave_type"):
            by_employee[allocation.employee_id].append(allocation)
        return by_employee

    def list(self, request, *args, **kwargs):
        user_company = request.user.get_active_company()
        queryset = self.get_queryset()

        employee_uid = request.query_params.get("employee")
        if employee_uid:
            queryset = queryset.filter(uid=employee_uid)
        work_location = request.query_params.get("work_location")
        if work_location:
            queryset = queryset.filter(work_locations__uid=work_location)

        employees = list(queryset)
        report = {
            "title": self.report_title,
            "subtitle": "Current balance for active employees",
            "company_name": user_company.name if user_company else "",
            **build_time_off(employees, self._allocations(employees)),
        }

        if request.query_params.get("keywords") == "overview":
            return Response({"employee_count": len(report["rows"])})

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, user_company)

        return Response(report, status=status.HTTP_200_OK)
