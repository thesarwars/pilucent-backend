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

from weapi.django_rest.helpers.dashboard.finance import open_bills_qs
from weapi.django_rest.helpers.reports.ap_aging_detail import ap_aging_detail

from ...serializers.reports.ap_aging_detail import (
    PrivateWeApAgingDetailRowSerializer,
)


class PrivateWeApAgingDetailReportView(ListAPIView):
    """A/P Aging Detail report: every open bill and unapplied vendor credit,
    grouped into aging bands with per-band subtotals and a grand total.

    Query params:
      * ``start_date`` / ``end_date`` (YYYY-MM-DD) -- optional period; the
        as-of date used for aging is ``end_date`` (else today, the "All Dates"
        view), and the range bounds which transactions are in scope.
      * ``keywords=overview`` -- return only the grand total (for a summary tile).
      * ``is_pdf=true`` -- render the report to PDF and return ``{file_uid, url}``.
    """

    serializer_class = PrivateWeApAgingDetailRowSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]

    def get_queryset(self):
        # The report is composite (bills + vendor credits) and is assembled in
        # list(); this queryset only backs the standard list/permission
        # machinery and DRF schema generation.
        return open_bills_qs(self.request.user.get_active_company())

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
        report = ap_aging_detail(
            company, as_of=as_of, start_date=start_date, end_date=end_date
        )

        if request.query_params.get("keywords", None) == "overview":
            return Response({"as_of": report["as_of"], "total": report["total"]})

        if request.query_params.get("is_pdf", None) == "true":
            pdf = get_pdf(
                self,
                True,
                {
                    # The resolved single aging date (get_pdf's own ``as_of`` is
                    # a raw start/end range, so the template uses this instead to
                    # label the header consistently with how the data was aged).
                    "report_as_of": report["as_of"],
                    "overview": report["total"],
                    "data": report["bands"],
                    "fields": [
                        "DATE",
                        "TRANSACTION TYPE",
                        "NUM",
                        "VENDOR",
                        "STORE",
                        "DUE DATE",
                        "PAST DUE",
                        "AMOUNT",
                        "OPEN BALANCE",
                    ],
                    "label": "ap_aging_detail",
                    "template": "reports/ap_aging_detail.html",
                    "is_report": True,
                    "title": "A/P Aging Detail Report",
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)
