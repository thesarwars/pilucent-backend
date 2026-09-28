"""Payroll summary **by employee** -- the pivoted report.

Sibling of `payroll_summary.py`, not a mode of it. That one answers "what did
each employee cost, in five buckets"; this one answers "what did each named line
item cost, per employee", which needs `payroll_type` preserved rather than
summed away. Reshaping the existing response would also break its consumers, so
this is its own endpoint.

The grid itself is built by
`payrollio.django_rest.helpers.payroll_summary_by_employee`, which keeps the
pivot testable without going through HTTP.
"""

import os
import tempfile

import weasyprint
from django.db.models import Max, Prefetch
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.date_range_filters import (
    DateFromToRangeFilter,
    WeekMonthYearRangeFilter,
)
from common.django_rest.permissions.company_subscription import HaveSubscription
from payrollio.django_rest.helpers.payroll_summary_by_employee import (
    build_payroll_summary_by_employee,
    resolve_pretax_deduction_names,
)
from payrollio.models import PayrollSalaryComponent, PayrollSalaryProcess
from recurringio.services.runner import resolve_timezone
from weapi.django_rest.serializers.payroll.reports.payroll_summary import (
    PayrollSummarySerializer,
)
from weapi.django_rest.serializers.payroll.reports.payroll_summary_by_employee import (
    PayrollSummaryByEmployeeFilter,
)


class PayrollSummaryByEmployeeReportView(generics.ListAPIView):
    serializer_class = PayrollSummarySerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"
    filterset_class = PayrollSummaryByEmployeeFilter
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    pagination_class = None  # A pivot is one object; paging it would split the grid.

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            PayrollSalaryProcess.objects.select_related(
                "employee", "employee__user", "employee__work_locations"
            )
            .prefetch_related(
                # The pivot reads every component of every run, so fetch them in
                # one query instead of one per run.
                Prefetch(
                    "payroll_components",
                    queryset=PayrollSalaryComponent.objects.only(
                        "payroll", "payroll_type", "payroll_category",
                        "current", "hours",
                    ),
                )
            )
            .filter(employee__user__companyuser__company=user_company)
            .order_by("employee__last_name", "employee__first_name", "pay_date")
        )

    def get_last_pay_date(self, user_company):
        last_pay_date = PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=user_company
        ).aggregate(Max("pay_date"))["pay_date__max"]
        if last_pay_date:
            return last_pay_date, last_pay_date
        return None, None

    def _resolve_dates(self, request, user_company):
        """(start, end, error_response) -- same contract as the sibling report."""
        start_date_str = request.query_params.get("date_from") or request.query_params.get(
            "pay_date_after"
        )
        end_date_str = request.query_params.get("date_to") or request.query_params.get(
            "pay_date_before"
        )

        if request.query_params.get("filter_type") == "last_pay_date":
            return (*self.get_last_pay_date(user_company), None)

        if not start_date_str and not end_date_str:
            return (*self.get_last_pay_date(user_company), None)

        start_date = None
        end_date = None
        for raw, label in ((start_date_str, "start"), (end_date_str, "end")):
            if not raw:
                continue
            try:
                parsed = parse_date(str(raw))
            except (ValueError, TypeError):
                parsed = None
            if not parsed:
                return (
                    None,
                    None,
                    Response(
                        {
                            "error": f"Invalid {label} date format. "
                            "Use YYYY-MM-DD format."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    ),
                )
            if label == "start":
                start_date = parsed
            else:
                end_date = parsed
        return start_date, end_date, None

    def _subtitle(self, request, start_date, end_date):
        """"From <date> to <date> for all employees from all locations".

        Narrows the wording when the caller filtered, so the header never
        claims a scope the numbers do not have.
        """
        scope = "for all employees"
        if request.query_params.get("employee"):
            scope = "for the selected employee"
        location = (
            "from all locations"
            if not request.query_params.get("work_location")
            else "from the selected location"
        )
        if start_date and end_date:
            span = (
                f"From {start_date.strftime('%b %d, %Y')} "
                f"to {end_date.strftime('%b %d, %Y')}"
            )
        elif start_date:
            span = f"From {start_date.strftime('%b %d, %Y')}"
        elif end_date:
            span = f"Through {end_date.strftime('%b %d, %Y')}"
        else:
            span = "For all dates"
        return f"{span} {scope} {location}"

    def list(self, request, *args, **kwargs):
        user_company = request.user.get_active_company()
        start_date, end_date, error = self._resolve_dates(request, user_company)
        if error is not None:
            return error

        queryset = self.filter_queryset(self.get_queryset())
        if start_date and end_date:
            queryset = queryset.filter(pay_date__range=(start_date, end_date))
        elif start_date:
            queryset = queryset.filter(pay_date__gte=start_date)
        elif end_date:
            queryset = queryset.filter(pay_date__lte=end_date)

        grid = build_payroll_summary_by_employee(
            queryset, pretax_names=resolve_pretax_deduction_names(user_company)
        )

        report = {
            "title": "Payroll summary by employee report",
            "subtitle": self._subtitle(request, start_date, end_date),
            "company_name": user_company.name if user_company else "",
            "date_from": start_date,
            "date_to": end_date,
            **grid,
        }

        if request.query_params.get("keywords") == "overview":
            # The Total column is not an employee.
            return Response({"employee_count": len(report["columns"]) - 1})

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, user_company)

        return Response(report, status=status.HTTP_200_OK)

    def _printed_at(self, company):
        """Footer stamp, in the company's own timezone.

        `Company.time_zone` is free text holding three different shapes, so it
        goes through the shared resolver rather than `ZoneInfo` directly -- a
        Hawaii company stamped in server time reads a day out.
        """
        zone = resolve_timezone(getattr(company, "time_zone", None))
        now = timezone.now().astimezone(zone)
        return now.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")

    def render_to_pdf(self, report, company):
        html_string = render_to_string(
            "reports/payrolls/payroll_summary_by_employee_temp.html",
            {
                "report": report,
                "printed_at": self._printed_at(company),
                # One employee fits portrait; a wide grid needs the extra
                # width or the columns crush together.
                "landscape": len(report["columns"]) > 4,
            },
        )
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_pdf.close()
        weasyprint.HTML(string=html_string).write_pdf(temp_pdf.name)
        with open(temp_pdf.name, "rb") as pdf_file:
            pdf_content = pdf_file.read()
        os.unlink(temp_pdf.name)
        response_pdf = HttpResponse(pdf_content, content_type="application/pdf")
        response_pdf["Content-Disposition"] = (
            "inline; filename=payroll_summary_by_employee_report.pdf"
        )
        return response_pdf
