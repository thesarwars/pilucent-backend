from datetime import date

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

from weapi.django_rest.helpers.dashboard.inventory import _inventory_products
from weapi.django_rest.helpers.reports.inventory_valuation_summary import (
    inventory_valuation_summary,
)

from ...serializers.reports.inventory_valuation_summary import (
    PrivateWeInventoryValuationSummaryRowSerializer,
)


class PrivateWeInventoryValuationSummaryReportView(ListAPIView):
    """Inventory Valuation Summary: one row per inventory item with on-hand
    quantity, cost value (Asset Value) and average unit cost (Calc. Avg), plus a
    weighted-average totals row.

    Valuation is a point-in-time snapshot taken as of *today* (the "All Dates"
    view); historical as-of valuation is not yet supported.

    Query params:
      * ``keywords=overview`` -- return only the totals row (for a summary tile).
      * ``is_pdf=true`` -- render the report to PDF and return ``{file_uid, url}``.
    """

    serializer_class = PrivateWeInventoryValuationSummaryRowSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]

    def get_queryset(self):
        # The report is assembled in list(); this queryset only backs the
        # standard list/permission machinery and DRF schema generation.
        return _inventory_products(self.request.user.get_active_company())

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        as_of = date.today()
        report = inventory_valuation_summary(company, as_of=as_of)

        if request.query_params.get("keywords", None) == "overview":
            return Response({"as_of": report["as_of"], "total": report["total"]})

        if request.query_params.get("is_pdf", None) == "true":
            pdf = get_pdf(
                self,
                True,
                {
                    "report_as_of": report["as_of"],
                    "data": report["rows"],
                    "overview": report["total"],
                    "fields": ["ITEM / PRODUCT", "SKU", "QTY", "ASSET VALUE", "CALC. AVG"],
                    "label": "inventory_valuation_summary",
                    "template": "reports/inventory_valuation_summary.html",
                    "is_report": True,
                    "title": "Inventory Valuation Summary",
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)
