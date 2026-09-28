from datetime import date

from django.utils.dateparse import parse_date

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

from weapi.django_rest.helpers.dashboard.finance import open_invoices_qs
from weapi.django_rest.helpers.reports.ar_aging_summary import ar_aging_summary

from ...serializers.reports.ar_aging_summary import (
    PrivateWeArAgingSummaryRowSerializer,
)


class PrivateWeArAgingSummaryReportView(ListAPIView):
    """A/R Aging Summary report: one rolled-up row per customer with its open
    balance spread across aging buckets, plus column totals and a grand total.

    Query params:
      * ``start_date`` / ``end_date`` (YYYY-MM-DD) -- optional period; the
        as-of date used for aging is ``end_date`` (else today, the "All Dates"
        view), and the range bounds which transactions are in scope.
      * ``keywords=overview`` -- return only the grand total + column totals.
      * ``is_pdf=true`` -- render the report to PDF and return ``{file_uid, url}``.
    """

    serializer_class = PrivateWeArAgingSummaryRowSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]

    def get_queryset(self):
        # The report is composite (invoices + credit memos) and is assembled in
        # list(); this queryset only backs the standard list/permission
        # machinery and DRF schema generation.
        return open_invoices_qs(self.request.user.get_active_company())

    def _date_params(self):
        def _parse(value):
            # parse_date raises ValueError for a well-formatted but out-of-range
            # date (e.g. 2026-13-99); treat any unparseable value as absent.
            try:
                return parse_date(value or "")
            except (ValueError, TypeError):
                return None

        start_date = _parse(self.request.query_params.get("start_date"))
        end_date = _parse(self.request.query_params.get("end_date"))
        as_of = end_date or date.today()
        return start_date, end_date, as_of

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        start_date, end_date, as_of = self._date_params()
        report = ar_aging_summary(
            company, as_of=as_of, start_date=start_date, end_date=end_date
        )

        if request.query_params.get("keywords", None) == "overview":
            return Response(
                {
                    "as_of": report["as_of"],
                    "column_totals": report["column_totals"],
                    "total": report["total"],
                }
            )

        if request.query_params.get("is_pdf", None) == "true":
            pdf = get_pdf(
                self,
                True,
                {
                    "report_as_of": report["as_of"],
                    "buckets": report["buckets"],
                    "data": report["rows"],
                    "column_totals": report["column_totals"],
                    "overview": {"total": report["total"]},
                    "label": "ar_aging_summary",
                    "template": "reports/ar_aging_summary.html",
                    "is_report": True,
                    "title": "A/R Aging Summary Report",
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)
