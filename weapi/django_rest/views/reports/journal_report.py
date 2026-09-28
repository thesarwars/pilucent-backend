from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import (
    DateFromToRangeFilter,
    WeekMonthYearRangeFilter,
)
from common.django_rest.permissions.company_subscription import HaveSubscription

from journalio.models import JournalEntryConnector, JournalEntry
from common.django_rest.helpers.ledger_balances import annotate_running_balance

from ....django_rest.serializers.reports.journal_report import (
    PrivateWeJournalReportListSerializer,
    GroupedJournalReportSerializer,
    PrivateJournalEntryWithConnectorsSerializer,
)


class PrivateWeJournalReportList(ListAPIView):
    serializer_class = PrivateWeJournalReportListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    ordering_fields = ["created_at"]
    search_fields = [
        "title",
        "first_name",
        "last_name",
        "display_name",
        "email",
        "mobile_number",
    ]
    ordering = "-created_at"
    filterset_fields = [
        "kind",
        "request_kind",
        "created_at",
    ]

    def get_queryset(self):
        """Journal lines for THIS company, in ledger order.

        Was `JournalEntryConnector.objects.all()` -- every tenant's lines, with
        no company filter at any layer. RLS does not cover this table: it is not
        in `RLS_TABLES` (companyio migration 0023) and carries no `company_id`
        column for the tenant policy to key on.
        """
        company = self.request.user.get_active_company()
        return annotate_running_balance(
            JournalEntryConnector.objects.filter(
                journal__company=company
            ).select_related("account")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        grouped_serializer = GroupedJournalReportSerializer(serializer.data)
        response = grouped_serializer.to_representation()
        return Response(response)


class PrivateWeJournalEntriesReport(ListAPIView):
    serializer_class = PrivateJournalEntryWithConnectorsSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    ordering_fields = ["created_at", "date"]
    search_fields = [
        "entry_number",
        "description",
        "kind",
    ]
    ordering = "-date"
    filterset_fields = [
        "kind",
        "status",
        "is_journal_entry",
        "is_transaction",
        "date",
    ]

    def get_queryset(self):
        queryset = JournalEntry.objects.filter(
            company=self.request.user.get_active_company(),
        )
        return queryset
