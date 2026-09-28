from django.db.models import Sum, Q
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.response import Response
from rest_framework.generics import ListAPIView

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountKindChoices

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import (
    DateFromToRangeFilter,
    WeekMonthYearRangeFilter,
)
from common.django_rest.permissions.company_subscription import HaveSubscription

from weapi.utils.net_income_calculator import NetIncomeCalculator

from ...serializers.reports.cash_flow import (
    PrivateWeCashFlowListSerializer,
)


class PrivateWeCashFlowReportList(ListAPIView):
    serializer_class = PrivateWeCashFlowListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    search_fields = [
        "uid",
        "title",
        "kind",
        "account_type__title",
        "detail_type__title",
        "status",
    ]
    filterset_fields = ["status", "kind", "account_type__title", "detail_type__title"]

    def get_queryset(self):
        return (
            ChartOfAccount.objects.get_status_all()
            .filter(
                company=self.request.user.get_active_company(),
                journalentryconnector__isnull=False,
            )
            .prefetch_related("journalentryconnector_set")
            .distinct()
        )

    def list(self, request, *args, **kwargs):
        

        if request.query_params.get("keywords", None) == "overview":
            return Response({})
        else:
            return super().list(request, *args, **kwargs)
