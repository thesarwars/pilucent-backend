from datetime import date

from django.utils.dateparse import parse_date

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from agencyio.models import Agency

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

from weapi.django_rest.helpers.reports.sales_tax_liability import sales_tax_liability

from ...serializers.reports.sales_tax_liability import (
    PrivateWeSalesTaxLiabilityRowSerializer,
)


class PrivateWeSalesTaxLiabilityReportView(ListAPIView):
    """Sales Tax Liability: sales tax collected/owed grouped by tax agency and its
    rate components (state/county/city/district), with Gross/Non-taxable/Taxable/Tax.
    The agency total sums Tax Amount only.

    Query params:
      * ``start_date`` / ``end_date`` (YYYY-MM-DD) -- the filing period (accrual
        basis); omit for All Dates.
      * ``keywords=overview`` -- return only the period grand total.
      * ``is_pdf=true`` -- render the report to PDF and return ``{file_uid, url}``.
    """

    serializer_class = PrivateWeSalesTaxLiabilityRowSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]

    def get_queryset(self):
        # The report is assembled in list(); this queryset only backs the
        # standard list/permission machinery and DRF schema generation.
        return Agency.objects.filter(company=self.request.user.get_active_company())

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
        report = sales_tax_liability(
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
                    "data": report["agencies"],
                    "overview": {"total": report["total"]},
                    "fields": [
                        "TAX NAME",
                        "GROSS TOTAL",
                        "NON-TAXABLE",
                        "TAXABLE AMOUNT",
                        "TAX AMOUNT",
                    ],
                    "label": "sales_tax_liability",
                    "template": "reports/sales_tax_liability.html",
                    "is_report": True,
                    "title": "Sales Tax Liability Report",
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)
