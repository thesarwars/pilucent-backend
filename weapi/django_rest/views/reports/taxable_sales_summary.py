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

from salesio.models import SaleItem

from weapi.django_rest.helpers.reports.taxable_sales_summary import (
    taxable_sales_summary,
)

from ...serializers.reports.taxable_sales_summary import (
    PrivateWeTaxableSalesItemSerializer,
)


class PrivateWeTaxableSalesSummaryReportView(ListAPIView):
    """Taxable Sales Summary: the taxable sales base (not the tax) grouped by
    product/service, with category subtotals, a no-item bucket, and a grand total.

    Query params:
      * ``start_date`` / ``end_date`` (YYYY-MM-DD) -- optional filing period
        (accrual basis); omit for All Dates.
      * ``keywords=overview`` -- return only the grand total (for a summary tile).
      * ``is_pdf=true`` -- render the report to PDF and return ``{file_uid, url}``.
    """

    serializer_class = PrivateWeTaxableSalesItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]

    def get_queryset(self):
        # The report is assembled in list(); this queryset only backs the
        # standard list/permission machinery and DRF schema generation.
        return SaleItem.objects.filter(
            sale__company=self.request.user.get_active_company(), is_tax=True
        )

    def _date_params(self):
        def _parse(value):
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
        report = taxable_sales_summary(
            company, as_of=as_of, start_date=start_date, end_date=end_date
        )

        if request.query_params.get("keywords", None) == "overview":
            return Response({"as_of": report["as_of"], "total": report["total"]})

        if request.query_params.get("is_pdf", None) == "true":
            pdf = get_pdf(
                self,
                True,
                {
                    "report_as_of": report["as_of"],
                    "data": report,
                    "overview": {"total": report["total"]},
                    "fields": ["PRODUCT / SERVICE", "TOTAL"],
                    "label": "taxable_sales_summary",
                    "template": "reports/taxable_sales_summary.html",
                    "is_report": True,
                    "title": "Taxable Sales Summary",
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)
