from django_filters.rest_framework import DjangoFilterBackend

from django.db import transaction

from rest_framework import filters

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
    ListAPIView,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.serializers.common import PrivateFileItemSerializer
from fileroomio.models import FileItem

from journalio.choices import JournalEntryStatusChoices
from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from weapi.django_rest.helpers.journal_entry_posting import (
    void_manual_journal_entry,
)

from journalio.models import JournalEntry, JournalEntryConnector

from common.django_rest.helpers.date_range_filters import (
    DateFromToRangeFilter,
    WeekMonthYearRangeFilter,
)
from common.django_rest.permissions.company_subscription import HaveSubscription
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from tagio.django_rest.serializers.common import PrivateTagSlimSerializer
from tagio.models import Tag

from ..serializers.journals import (
    PrivateWeJournalEntryListSerializer,
    PrivateWeJournalEntryDetailsSerializer,
    PrivateWeUndepositedFundsJournalEntryConnectorSerializer,
)


class PrivateWeJournalEntryList(ListCreateAPIView):
    serializer_class = PrivateWeJournalEntryListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_journal_entry"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    ordering_fields = ["created_at"]
    search_fields = [
        "entry_number",
        "description",
        "date",
        "journalentryconnector__supplier__first_name",
        "journalentryconnector__supplier__last_name",
        "journalentryconnector__customer__first_name",
        "journalentryconnector__customer__last_name",
        "journalentryconnector__account__title",
        # "journalentryconnector__warehose__title",
        # "journalentryconnector__account__kind",
    ]
    filterset_fields = [
        "is_deposit",
        "status",
        "journalentryconnector__account__uid",
        "journalentryconnector__kind",
    ]

    def get_queryset(self):
        return JournalEntry.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeJournalEntryDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeJournalEntryDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            JournalEntry.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs.get("uid"),
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Cancel the entry, then retire it.

        This was the two lines below and nothing else. `update_opening_balance`
        appears once in the manual journal-entry serializer -- in `create` -- so
        deleting an entry left every account it touched still carrying the
        figure the original posting put there, with the entry gone from the list
        and from the register. Nothing reported it; it simply became drift.

        Refused when a closed reconciliation has ticked one of these legs, the
        same guard the five document deletes take.

        Locked for the same reason they lock: the status is read here and acted
        on below, and two concurrent deletes would otherwise both reverse.
        """
        entry = JournalEntry.objects.select_for_update().get(pk=instance.pk)
        if entry.status == JournalEntryStatusChoices.REMOVED:
            return

        assert_not_reconciled(
            JournalEntry.objects.filter(pk=entry.pk), action="delete"
        )

        void_manual_journal_entry(
            entry, created_by=self.request.user.get_employee()
        )

        entry.status = JournalEntryStatusChoices.REMOVED
        entry.save(update_fields=["status"])


class PrivateWeJournalEntryTagList(ListCreateAPIView):
    serializer_class = PrivateTagSlimSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return Tag.objects.filter(
            id__in=(
                get_object_or_404(
                    JournalEntry.objects.get_status_all(),
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs.get("uid"),
                ).tagconnector_set.values_list("tag_id", flat=True)
            )
        )


class PrivateWeJournalEntryFileItemList(ListCreateAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return FileItem.objects.filter(
            id__in=(
                get_object_or_404(
                    JournalEntry.objects.get_status_all().filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.JOURNAL_ENTRY
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWeUndepositedFundsJournalEntryList(ListAPIView):
    serializer_class = PrivateWeUndepositedFundsJournalEntryConnectorSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_journal_entry"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    ordering_fields = ["created_at"]
    search_fields = [
        "journal__entry_number",
        "journal__description",
        "journal__date",
    ]
    filterset_fields = [
        "kind",
        "journal__status",
    ]

    def get_queryset(self):
        company = self.request.user.get_active_company()

        # Get the "Undeposited Funds" chart of account
        chart_of_accounts = get_chart_of_account(
            ["Undeposited Funds"],
            company,
        )
        undeposited_funds_account = chart_of_accounts.get("Undeposited Funds")

        if not undeposited_funds_account:
            return JournalEntryConnector.objects.none()

        return (
            JournalEntryConnector.objects.select_related(
                "journal", "account", "customer", "supplier"
            )
            .filter(
                account=undeposited_funds_account,
                journal__company=company,
                journal__is_deposit=True,
            )
            .filter(
                journal__status__in=[
                    JournalEntryStatusChoices.DRAFT,
                    JournalEntryStatusChoices.PUBLISHED,
                ]
            )
        )
