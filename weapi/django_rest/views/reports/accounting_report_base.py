"""Shared shell for the new accounting comparison / pivot reports.

Mirrors `weapi.django_rest.views.payroll.reports.base` -- same permissions,
same date handling, same PDF path -- so the accounting reports take the query
string the frontend specs asked for and return the payload shape the payroll
reports already established.
"""

import os
import tempfile

import weasyprint
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.permissions.company_subscription import HaveSubscription
from recurringio.services.runner import resolve_timezone


class AccountingReportView(APIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"

    report_title = ""
    pdf_template = ""
    pdf_filename = "report.pdf"

    def build_report(self, request, company):
        raise NotImplementedError

    # -- dates -------------------------------------------------------------

    def _date(self, request, *names):
        """First present value among `names`, parsed. Raises ValueError if bad."""
        for name in names:
            raw = request.query_params.get(name)
            if not raw:
                continue
            parsed = parse_date(str(raw))
            if not parsed:
                raise ValueError(name)
            return parsed
        return None

    def resolve_range(self, request, prefix=""):
        """(date_from, date_to) for a prefixed pair.

        Accepts both the `date_from`/`date_to` naming the newer specs use and
        the `start_date`/`end_date` naming the existing profit-loss endpoint
        takes, so a caller can use either.
        """
        if prefix:
            return (
                self._date(request, f"{prefix}date_from", f"{prefix}start_date"),
                self._date(request, f"{prefix}date_to", f"{prefix}end_date"),
            )
        return (
            self._date(request, "date_from", "start_date"),
            self._date(request, "date_to", "end_date"),
        )

    # -- request -----------------------------------------------------------

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        try:
            report = self.build_report(request, company)
        except ValueError as error:
            return Response(
                {"error": f"Invalid {error} format. Use YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report.setdefault("title", self.report_title)
        report.setdefault("company_name", company.name if company else "")

        overview = self.overview(request, report)
        if overview is not None:
            return overview

        if request.query_params.get("is_pdf") == "true":
            return self.render_to_pdf(report, company)
        return Response(report, status=status.HTTP_200_OK)

    def overview(self, request, report):
        return None

    # -- pdf ---------------------------------------------------------------

    def render_to_pdf(self, report, company):
        html_string = render_to_string(
            self.pdf_template,
            {"report": report, "printed_at": self.printed_at(company)},
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
        zone = resolve_timezone(getattr(company, "time_zone", None))
        return (
            timezone.now().astimezone(zone).strftime("%b %d, %Y %I:%M %p")
            .replace(" 0", " ")
        )


def format_span(date_from, date_to):
    """"From Jun 1 to Jun 30, 2026" -- the wording the specs use."""
    if date_from and date_to:
        if date_from.year == date_to.year:
            return (
                f"From {date_from.strftime('%b %-d')} "
                f"to {date_to.strftime('%b %-d, %Y')}"
            )
        return (
            f"From {date_from.strftime('%b %-d, %Y')} "
            f"to {date_to.strftime('%b %-d, %Y')}"
        )
    if date_from:
        return f"From {date_from.strftime('%b %-d, %Y')}"
    if date_to:
        return f"Through {date_to.strftime('%b %-d, %Y')}"
    return "All dates"


def shift_year(value, years=1):
    """The same date a year earlier, clamped for Feb 29."""
    if value is None:
        return None
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)
