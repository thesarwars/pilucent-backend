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
from weapi.django_rest.helpers.reports.inventory_valuation_detail import (
    inventory_valuation_detail,
)

from ...serializers.reports.inventory_valuation_detail import (
    PrivateWeInventoryValuationDetailRowSerializer,
)


class PrivateWeInventoryValuationDetailReportView(ListAPIView):
    """Inventory Valuation Detail: a transaction-by-transaction ledger per
    inventory item (movements in date order) with signed quantity, per-line rate,
    FIFO inventory cost, and the running quantity-on-hand and asset value after
    each line, grouped by product with a subtotal per item and a grand total.

    Read straight from the ``StockMovement`` ledger, so it is accurate from the
    OPENING seed forward.

    Query params:
      * ``keywords=overview`` -- return only the grand total.
      * ``is_pdf=true`` -- render the report to PDF and return ``{file_uid, url}``.
    """

    serializer_class = PrivateWeInventoryValuationDetailRowSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]

    def get_queryset(self):
        # The report is assembled in list(); this queryset only backs the
        # standard list/permission machinery and DRF schema generation.
        return _inventory_products(self.request.user.get_active_company())

    def _resolve_as_of(self, request):
        """As-of date from ``end_date`` / ``date_before`` (YYYY-MM-DD), else today."""
        raw = request.query_params.get("end_date") or request.query_params.get(
            "date_before"
        )
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
        return date.today()

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        as_of = self._resolve_as_of(request)
        report = inventory_valuation_detail(company, as_of=as_of)

        if request.query_params.get("keywords", None) == "overview":
            return Response({"as_of": report["as_of"], "total": report["total"]})

        if request.query_params.get("is_pdf", None) == "true":
            pdf = get_pdf(
                self,
                True,
                {
                    "report_as_of": report["as_of"],
                    "data": report["groups"],
                    "overview": report["total"],
                    "fields": [
                        "DATE",
                        "TYPE",
                        "QTY",
                        "RATE",
                        "INVENTORY COST",
                        "QTY ON HAND",
                        "ASSET VALUE",
                    ],
                    "label": "inventory_valuation_detail",
                    "template": "reports/inventory_valuation_detail.html",
                    "is_report": True,
                    "title": "Inventory Valuation Detail",
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)
