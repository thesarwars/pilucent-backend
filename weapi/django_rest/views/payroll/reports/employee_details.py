"""Employee details -- master data, not a pay run.

Unlike its siblings this report reads `Employee` rather than
`PayrollSalaryProcess`, and takes no date range: the reference subtitle is "For
all employees from all locations". It inherits the base only for the PDF path
and the timezone-correct footer.

Each employee needs six satellites (address, banking, deductions,
contributions, leave allocations, tax rows). Fetching them per row would be
roughly `6 x headcount` queries, so they are gathered in one pass each and
handed to the builder as a lookup.

The payload is PII-bearing but masked -- see
`payrollio.django_rest.helpers.employee_details` for what is withheld.
"""

from collections import defaultdict

from addressio.models import Address
from django.db.models import Prefetch
from employeeio.models import (
    Employee,
    EmployeeBankingInformation,
    EmployeeDeductionContribution,
    EmployeeTax,
)
from leaveio.models import EmployeeLeaveAllocation
from rest_framework import status
from rest_framework.response import Response

from payrollio.django_rest.helpers.employee_details import build_employee_details
from weapi.django_rest.views.payroll.reports.base import PayrollReportView


class EmployeeDetailsReportView(PayrollReportView):
    report_title = "Employee details report"
    pdf_template = "reports/payrolls/employee_details_temp.html"
    pdf_filename = "employee_details_report.pdf"
    filterset_class = None  # The sibling filterset targets PayrollSalaryProcess.
    filter_backends = []

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            Employee.objects.select_related("user", "work_locations")
            .filter(user__companyuser__company=user_company)
            .distinct()
        )

    def _subtitle_for(self, request):
        """No date span -- this report describes people, not a period."""
        scope = (
            "For the selected employee"
            if request.query_params.get("employee")
            else "For all employees"
        )
        location = (
            "from the selected location"
            if request.query_params.get("work_location")
            else "from all locations"
        )
        return f"{scope} {location}"

    def _related(self, employees):
        """Every satellite for every employee, in a fixed number of queries."""
        employee_ids = [employee.id for employee in employees]
        facts = {employee_id: {} for employee_id in employee_ids}
        if not employee_ids:
            return facts

        # One address per employee is enough for the report, and production has
        # duplicate connectors pointing at the same address, so the first wins.
        for connector in (
            Address.objects.filter(addressconnector__employee_id__in=employee_ids)
            .values_list("addressconnector__employee_id", "id")
            .order_by("addressconnector__employee_id", "id")
        ):
            facts[connector[0]].setdefault("address_id", connector[1])
        address_ids = {
            entry["address_id"] for entry in facts.values() if entry.get("address_id")
        }
        addresses = {
            address.id: address
            for address in Address.objects.filter(id__in=address_ids)
        }
        for entry in facts.values():
            entry["address"] = addresses.get(entry.pop("address_id", None))

        for banking in EmployeeBankingInformation.objects.filter(
            employee_id__in=employee_ids
        ).order_by("employee_id", "id"):
            facts[banking.employee_id].setdefault("banking", banking)

        deductions = defaultdict(list)
        contributions = defaultdict(list)
        for row in EmployeeDeductionContribution.objects.filter(
            employee_id__in=employee_ids
        ).select_related("deduction_and_contribution"):
            # A single setup row can carry both an employee deduction and a
            # company contribution, so it may appear under both headings.
            deductions[row.employee_id].append(row)
            contributions[row.employee_id].append(row)

        allocations = defaultdict(list)
        for allocation in EmployeeLeaveAllocation.objects.filter(
            employee_id__in=employee_ids
        ).select_related("leave_type"):
            allocations[allocation.employee_id].append(allocation)

        tax_rows = defaultdict(list)
        for tax_row in EmployeeTax.objects.filter(
            employee_id__in=employee_ids
        ).order_by("employee_id", "id"):
            tax_rows[tax_row.employee_id].append(tax_row)

        for employee_id, entry in facts.items():
            entry["deductions"] = deductions.get(employee_id, [])
            entry["contributions"] = contributions.get(employee_id, [])
            entry["allocations"] = allocations.get(employee_id, [])
            entry["tax_rows"] = tax_rows.get(employee_id, [])
        return facts

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
            "subtitle": self._subtitle_for(request),
            "company_name": user_company.name if user_company else "",
            **build_employee_details(employees, related=self._related(employees)),
        }

        if request.query_params.get("keywords") == "overview":
            return Response({"employee_count": len(report["rows"])})

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, user_company)

        return Response(report, status=status.HTTP_200_OK)
