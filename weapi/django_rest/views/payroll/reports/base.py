"""Shared shell for the payroll report endpoints.

Date resolution, the subtitle, permissions and the PDF path are identical across
these reports and were copied three times before this existed. A subclass
supplies a title, a template and a `build_report`; everything else is inherited.

`PayrollSummaryReportView` and `PayrollSummaryByEmployeeReportView` deliberately
stay outside this base: they mount `DateFromToRangeFilter` and
`WeekMonthYearRangeFilter`, which filter `created_at` rather than `pay_date`.
That is a trap on a payroll report (see `payroll_details`), so the base does not
carry it and the newer reports do not inherit it.
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
from payrollio.models import PayrollSalaryComponent, PayrollSalaryProcess
from recurringio.services.runner import resolve_timezone
from weapi.django_rest.serializers.payroll.reports.payroll_summary import (
    PayrollSummarySerializer,
)
from weapi.django_rest.serializers.payroll.reports.payroll_summary_by_employee import (
    PayrollSummaryByEmployeeFilter,
)


class PayrollReportView(generics.ListAPIView):
    serializer_class = PayrollSummarySerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"
    filterset_class = PayrollSummaryByEmployeeFilter
    filter_backends = [DjangoFilterBackend]
    pagination_class = None  # A report is one object; paging would split it.

    report_title = ""
    pdf_template = ""
    pdf_filename = "payroll_report.pdf"
    # Whether the subtitle carries a "for all employees" clause. The tax
    # reports never name an employee, so theirs reads "From … from all
    # locations".
    subtitle_names_employees = True
    # Extra columns a subclass's builder reads off each run.
    payroll_fields = ()
    component_fields = ("payroll", "payroll_type", "payroll_category", "current")

    def build_report(self, request, payrolls, context):
        raise NotImplementedError

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        queryset = PayrollSalaryProcess.objects.prefetch_related(
            Prefetch(
                "payroll_components",
                queryset=PayrollSalaryComponent.objects.only(*self.component_fields),
            )
        ).filter(employee__user__companyuser__company=user_company)
        if self.payroll_fields:
            queryset = queryset.select_related(*self.payroll_fields)
        return queryset

    def get_last_pay_date(self, user_company):
        last_pay_date = PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=user_company
        ).aggregate(Max("pay_date"))["pay_date__max"]
        if last_pay_date:
            return last_pay_date, last_pay_date
        return None, None

    def resolve_dates(self, request, user_company):
        """(start, end, error_response).

        `filter_type=last_pay_date` wins; then `date_from`/`date_to`, falling
        back to the legacy `pay_date_after`/`pay_date_before`; with nothing at
        all it defaults to the last pay date rather than all time.
        """
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

    def subtitle(self, request, start_date, end_date):
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

        parts = [span]
        if self.subtitle_names_employees:
            parts.append(
                "for the selected employee"
                if request.query_params.get("employee")
                else "for all employees"
            )
        parts.append(
            "from the selected location"
            if request.query_params.get("work_location")
            else "from all locations"
        )
        return " ".join(parts)

    def list(self, request, *args, **kwargs):
        user_company = request.user.get_active_company()
        start_date, end_date, error = self.resolve_dates(request, user_company)
        if error is not None:
            return error

        queryset = self.filter_queryset(self.get_queryset())
        if start_date and end_date:
            queryset = queryset.filter(pay_date__range=(start_date, end_date))
        elif start_date:
            queryset = queryset.filter(pay_date__gte=start_date)
        elif end_date:
            queryset = queryset.filter(pay_date__lte=end_date)

        context = {
            "company": user_company,
            "date_from": start_date,
            "date_to": end_date,
        }
        report = {
            "title": self.report_title,
            "subtitle": self.subtitle(request, start_date, end_date),
            "company_name": user_company.name if user_company else "",
            "date_from": start_date,
            "date_to": end_date,
            **self.build_report(request, queryset, context),
        }

        overview = self.overview(request, report)
        if overview is not None:
            return overview

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, user_company)
        return Response(report, status=status.HTTP_200_OK)

    def overview(self, request, report):
        """`keywords=overview` response, or None to fall through."""
        return None

    def pdf_context(self, report):
        return {}

    def render_to_pdf(self, report, company):
        html_string = render_to_string(
            self.pdf_template,
            {
                "report": report,
                "printed_at": self.printed_at(company),
                **self.pdf_context(report),
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
            f"inline; filename={self.pdf_filename}"
        )
        return response_pdf

    def printed_at(self, company):
        """Footer stamp, in the company's own timezone.

        `Company.time_zone` is free text holding three different shapes, so it
        goes through the shared resolver rather than `ZoneInfo` directly -- a
        Hawaii company stamped in server time reads a day out.
        """
        zone = resolve_timezone(getattr(company, "time_zone", None))
        now = timezone.now().astimezone(zone)
        return now.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
