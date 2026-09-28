from django.db.models import Sum, Q

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.response import Response
from rest_framework.generics import ListAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

from customerio.models import Customer

from ...serializers.reports.customer_reports import (
    PrivateWeCustomerBalanceSheetSummaryReportSerializer,
)

from journalio.models import JournalEntryConnector


class PrivateWeCustomerBalanceSheetSummaryReportView(ListAPIView):
    serializer_class = PrivateWeCustomerBalanceSheetSummaryReportSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    filterset_fields = ["title", "status"]
    search_fields = filterset_fields + ["uid"]

    def get_queryset(self):
        return Customer.objects.get_status_active()
