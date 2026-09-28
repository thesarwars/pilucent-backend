"""Tax liability -- what the company owes each taxing authority.

Organised by filing group rather than by employee, reusing the grouping
`payroll_journal_mappings` already owns so this report, the journal poster and
the Tax Center cannot disagree about what belongs on a 941.

Date handling, permissions and the PDF path mirror the other payroll reports.
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
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    resolve_state_from_general_tax_setting,
)
from payrollio.django_rest.helpers.payroll_tax_liability import (
    build_tax_liability,
    resolve_paid_by_group,
)
from payrollio.models import PayrollSalaryComponent, PayrollSalaryProcess
from recurringio.services.runner import resolve_timezone
from weapi.django_rest.serializers.payroll.reports.payroll_summary import (
    PayrollSummarySerializer,
)
from weapi.django_rest.serializers.payroll.reports.payroll_summary_by_employee import (
    PayrollSummaryByEmployeeFilter,
)


PAYMENTS_NOTE = (
    "Payments are recorded against a filing group, not an individual tax. "
    "A line's paid figure is a pro-rata share of its group's."
)


class PayrollTaxLiabilityReportView(generics.ListAPIView):
    serializer_class = PayrollSummarySerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"
    filterset_class = PayrollSummaryByEmployeeFilter
    # See the note in payroll_details: the sibling reports' extra date backends
    # filter `created_at`, not `pay_date`.
    filter_backends = [DjangoFilterBackend]
    pagination_class = None

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            PayrollSalaryProcess.objects.prefetch_related(
                Prefetch(
                    "payroll_components",
                    queryset=PayrollSalaryComponent.objects.only(
                        "payroll", "payroll_type", "payroll_category", "current"
                    ),
                )
            )
            # No employee joins: this report never names one. Only the
            # components are read.
            .filter(employee__user__companyuser__company=user_company)
        )

    def get_last_pay_date(self, user_company):
        last_pay_date = PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=user_company
        ).aggregate(Max("pay_date"))["pay_date__max"]
        if last_pay_date:
            return last_pay_date, last_pay_date
        return None, None

    def _resolve_dates(self, request, user_company):
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
        """No "for all employees" clause -- this report never names one."""
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
        return f"{span} {location}"

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

        state_code = resolve_state_from_general_tax_setting(user_company)
        paid_by_group, attribution = resolve_paid_by_group(
            user_company, state_code=state_code,
            date_from=start_date, date_to=end_date,
        )

        report = {
            "title": "Tax liability report",
            "subtitle": self._subtitle(request, start_date, end_date),
            "company_name": user_company.name if user_company else "",
            "state_code": state_code or "",
            "date_from": start_date,
            "date_to": end_date,
            "payments_note": PAYMENTS_NOTE,
            "payments_attributed": attribution,
            **build_tax_liability(
                queryset, state_code=state_code, paid_by_group=paid_by_group
            ),
        }

        if request.query_params.get("keywords") == "overview":
            return Response(
                {"group_count": sum(1 for row in report["rows"] if row["is_group"])}
            )

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, user_company)

        return Response(report, status=status.HTTP_200_OK)

    def render_to_pdf(self, report, company):
        html_string = render_to_string(
            "reports/payrolls/payroll_tax_liability_temp.html",
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
            "inline; filename=payroll_tax_liability_report.pdf"
        )
        return response_pdf

    def _printed_at(self, company):
        zone = resolve_timezone(getattr(company, "time_zone", None))
        now = timezone.now().astimezone(zone)
        return now.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
