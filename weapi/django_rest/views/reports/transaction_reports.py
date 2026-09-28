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

from journalio.models import JournalEntryConnector
from common.django_rest.helpers.ledger_balances import annotate_running_balance

from ...serializers.reports.transaction_reports import (
    PrivateWeTrialBalanceListSerializer,
    PrivateWeTransactionListSerializer,
)

import logging

logger = logging.getLogger(__name__)


class PrivateWeTrialBalanceList(ListAPIView):
    serializer_class = PrivateWeTrialBalanceListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    search_fields = ["uid", "title", "kind"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        company = self.request.user.get_active_company()
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

    def get_total_debit_and_credit(self, queryset):
        total_debit = total_credit = 0
        for chart_of_account in queryset:
            total_debit += chart_of_account.get_total_debit()
            total_credit += chart_of_account.get_total_credit()
        return total_debit, total_credit

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if request.query_params.get("keywords", None) == "overview":
            total_debit, total_credit = self.get_total_debit_and_credit(queryset)
            return Response({"total_debit": total_debit, "total_credit": total_credit})

        if request.query_params.get("is_pdf", None) == "true":
            total_debit, total_credit = self.get_total_debit_and_credit(queryset)

            # Creating PDF
            pdf = get_pdf(
                self,
                True,
                {
                    "overview": {
                        "total_debit": total_debit,
                        "total_credit": total_credit,
                    },
                    "data": self.get_serializer(queryset, many=True).data,
                    "fields": ["FULL NAME", "DEBIT", "CREDIT"],
                    "label": "trial_balance",
                    "template":"reports/trial_balance.html",
                    "is_report":True,
                    "title": "Profit And Loss Report",
                },
            )
            return Response(
                {
                    "file_uid": pdf.uid,
                    "url": pdf.file.url,
                }
            )
        return super().list(request, *args, **kwargs)


class PrivateWeTransactionList(ListAPIView):
    serializer_class = PrivateWeTransactionListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    search_fields = ["uid", "title", "kind"]
    filterset_fields = ["kind"]

    def base_queryset(self):
        """The rows, without the running-balance window.

        Split out because the overview branch aggregates over these, and an
        aggregate on top of a window function is a different and much more
        awkward query than an aggregate on plain rows.
        """
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        queryset = JournalEntryConnector.objects.filter(
            journal__company=self.request.user.get_active_company()
        )
        if start_date and end_date:
            # The line's own transaction date, not the row's insertion
            # timestamp -- a backdated document belongs to the period it is
            # dated in, not the one it was typed in.
            queryset = queryset.filter(date__range=[start_date, end_date])
        return queryset

    def get_queryset(self):
        return annotate_running_balance(
            self.base_queryset().select_related("account")
        )

    def list(self, request, *args, **kwargs):
        return (
            Response(
                self.base_queryset().aggregate(
                    total_debit=Sum("debit"),
                    total_credit=Sum("credit"),
                )
            )
            if request.query_params.get("keywords", None) == "overview"
            else super().list(request, *args, **kwargs)
        )
