from django.db.models import Sum, Q
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from accounts.models import ChartOfAccount

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription

from ...serializers.reports.payroll_cost_reports import (
    PrivateWePayrollCostReportListSerializer,
)

import logging

logger = logging.getLogger(__name__)


class PrivateWePayrollCostReportList(ListAPIView):
    serializer_class = PrivateWePayrollCostReportListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    search_fields = ["uid", "title", "kind"]
    filterset_fields = ["status", "kind", "parent__title", "detail_type__title"]

    def get_queryset(self):
        company = self.request.user.get_active_company()
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        queryset = (
            ChartOfAccount.objects.get_status_all()
            .filter(Q(company=company, journalentryconnector__isnull=False))
            .prefetch_related("journalentryconnector_set")
            .distinct()
        )
        if start_date and end_date:
            queryset = queryset.filter(
                journalentryconnector__created_at__range=[start_date, end_date]
            )

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        payroll_expense_cao = self.get_serializer(
            queryset.filter(Q(detail_type__title="Payroll Expenses")), many=True
        ).data
        company_contribution_cao = self.get_serializer(
            queryset.filter(Q(parent__title="Company Contributions")), many=True
        ).data
        payroll_liabilities_cao = self.get_serializer(
            queryset.filter(Q(detail_type__title="Payroll Liabilities")), many=True
        ).data

        overview = {
            "total_payroll_expense_cao": sum(
                data["last_balance"] for data in payroll_expense_cao
            ),
            "total_company_contribution_cao": sum(
                data["last_balance"] for data in company_contribution_cao
            ),
            "total_payroll_liabilities_cao": sum(
                data["last_balance"] for data in payroll_liabilities_cao
            ),
        }

        if request.query_params.get("keywords", None) == "overview":
            return Response(overview)

        if request.query_params.get("is_pdf", None) == "true":

            # Creating PDF
            pdf = get_pdf(
                self,
                True,
                {
                    "overview": overview,
                    "data": {
                        "payroll_expense_cao": payroll_expense_cao,
                        "company_contribution_cao": company_contribution_cao,
                        "payroll_liabilities_cao": payroll_liabilities_cao,
                    },
                    "fields": [],
                    "label": "total_payroll_cost_report",
                    "template": "reports/payrolls/payroll_cost_report.html",
                    "is_report": True,
                    "title": "Total payroll cost report",
                },
            )
            return Response(
                {
                    "file_uid": pdf.uid,
                    "url": pdf.file.url,
                }
            )
        return super().list(request, *args, **kwargs)
