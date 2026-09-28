"""Payroll details -- one row per payroll run.

The transpose of `payroll_summary_by_employee`: same figures, but a run per row
with the line items nested inside each cell, so an employee paid twice in the
range shows both runs instead of one merged column.

Date handling, permissions and the PDF path mirror the by-employee report
deliberately -- the two are picked from the same report menu and should take the
same query string.
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
from rest_framework import generics, status
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.permissions.company_subscription import HaveSubscription
from payrollio.django_rest.helpers.payroll_details import (
    build_payroll_details,
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


class PayrollDetailsReportView(generics.ListAPIView):
    serializer_class = PayrollSummarySerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"
    filterset_class = PayrollSummaryByEmployeeFilter
    # Only DjangoFilterBackend. The sibling reports also mount SearchFilter,
    # DateFromToRangeFilter and WeekMonthYearRangeFilter, but on a payroll
    # report those last two filter `created_at` -- when the run was *entered* --
    # rather than `pay_date`, which reads as a bug from the report screen.
    # SearchFilter is a no-op without `search_fields`.
    filter_backends = [DjangoFilterBackend]
    pagination_class = None  # One report object; paging would split the rows.

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            PayrollSalaryProcess.objects.select_related(
                "employee", "employee__user", "employee__work_locations"
            )
            .prefetch_related(
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
        """(start, end, error_response) -- same contract as the sibling reports."""
        start_date_str = request.query_params.get(
            "date_from"
        ) or request.query_params.get("pay_date_after")
        end_date_str = request.query_params.get(
            "date_to"
        ) or request.query_params.get("pay_date_before")

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
        scope = (
            "for the selected employee"
            if request.query_params.get("employee")
            else "for all employees"
        )
        location = (
            "from the selected location"
            if request.query_params.get("work_location")
            else "from all locations"
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

        report = {
            "title": "Payroll details report",
            "subtitle": self._subtitle(request, start_date, end_date),
            "company_name": user_company.name if user_company else "",
            "date_from": start_date,
            "date_to": end_date,
            **build_payroll_details(
                queryset, pretax_names=resolve_pretax_deduction_names(user_company)
            ),
        }

        if request.query_params.get("keywords") == "overview":
            # The Total row is not a payroll run.
            return Response({"payroll_count": len(report["rows"]) - 1})

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, user_company)

        return Response(report, status=status.HTTP_200_OK)

    def render_to_pdf(self, report, company):
        html_string = render_to_string(
            "reports/payrolls/payroll_details_temp.html",
            {"report": report, "printed_at": self._printed_at(company)},
        )
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_pdf.close()
        weasyprint.HTML(string=html_string).write_pdf(temp_pdf.name)
        with open(temp_pdf.name, "rb") as pdf_file:
            pdf_content = pdf_file.read()
        os.unlink(temp_pdf.name)
        response_pdf = HttpResponse(pdf_content, content_type="application/pdf")
        response_pdf["Content-Disposition"] = (
            "inline; filename=payroll_details_report.pdf"
        )
        return response_pdf

    def _printed_at(self, company):
        """Footer stamp, in the company's own timezone.

        `Company.time_zone` is free text holding three different shapes, so it
        goes through the shared resolver rather than `ZoneInfo` directly -- a
        Hawaii company stamped in server time reads a day out.
        """
        zone = resolve_timezone(getattr(company, "time_zone", None))
        now = timezone.now().astimezone(zone)
        return now.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
