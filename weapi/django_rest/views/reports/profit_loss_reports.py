from collections import defaultdict
from decimal import Decimal

from django.db.models import Q

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.response import Response
from rest_framework.generics import ListAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from accounts.models import ChartOfAccount
from weapi.django_rest.helpers.reports.account_activity import has_journal_line
from weapi.django_rest.helpers.reports.profit_loss_engine import (
    COGS,
    EXPENSES,
    INCOME,
    OTHER_EXPENSES,
    OTHER_INCOME,
    PAYROLL_EXPENSES,
    TOTAL_KEY,
    collect,
)
from accounts.choices import ChartOfAccountKindChoices

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

from ...serializers.reports.profit_loss_reports import (
    PrivateWeProfitLossListSerializer,
)


class PrivateWeProfitLossList(ListAPIView):
    serializer_class = PrivateWeProfitLossListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    filterset_fields = [
        "title",
        "status",
        "kind",
        "account_type__title",
        "detail_type__title",
    ]
    search_fields = filterset_fields + ["uid"]

    def get_expense_accounts(self, queryset):
        return queryset.filter(
            Q(kind=ChartOfAccountKindChoices.EXPENSES)
            & ~Q(account_type__title="Cost of Goods Sold (COGS)")
            & ~Q(account_type__title="Other Expenses")
        )

    def get_queryset(self):
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        kind = self.request.query_params.get("kind")

        # Each of these was a chained .filter() on the same multi-valued
        # relation, and Django resolves every one as its own join -- with all
        # four applied the intermediate is accounts x lines x lines x lines x
        # lines before .distinct() collapses it. As Exists subqueries there is
        # no fan-out and nothing to deduplicate.
        #
        # Kept as separate Exists rather than one combined subquery on purpose:
        # chained filters match "has a line in range AND has a line for this
        # customer", which may be different lines. Merging them would quietly
        # narrow the report.
        queryset = (
            ChartOfAccount.objects.get_status_all()
            .filter(company=self.request.user.get_active_company())
            .prefetch_related("journalentryconnector_set")
            .filter(has_journal_line())
        )
        if start_date and end_date:
            queryset = queryset.filter(
                has_journal_line(created_at__range=[start_date, end_date])
            )

        if customer_uid := self.request.query_params.get("customer_uid"):
            queryset = queryset.filter(has_journal_line(customer__uid=customer_uid))
        if warehouse_uid := self.request.query_params.get("warehouse_uid"):
            queryset = queryset.filter(has_journal_line(warehose__uid=warehouse_uid))
        if kind == ChartOfAccountKindChoices.EXPENSES:
            queryset = self.get_expense_accounts(queryset)
        return queryset

    def get_serializer_context(self):
        """Hand every row its period movement.

        The rows have to move to the journal in the same breath as the totals.
        Leaving them on `opening_balance` while the totals came from the ledger
        would print lines that do not add up to the figure above them, which is
        worse than either source alone.
        """
        context = super().get_serializer_context()
        if getattr(self, "_period_amounts", None) is not None:
            context["period_amounts"] = self._period_amounts
        return context

    def period_amounts(self, request):
        """`{account uid: signed amount}` for the requested period.

        From the journal lines, not from `ChartOfAccount.opening_balance`.

        The stored column is a lifetime running balance with no date axis, so
        the old aggregate could not answer a period question no matter how the
        query was written: `get_queryset` narrowed WHICH ACCOUNTS APPEARED to
        those with a line in range -- `has_journal_line` is an `Exists`,
        contributing no amount -- and then summed each survivor's whole-life
        balance. Two adjacent months returned identical figures for any account
        touched in both, on a company with perfect books and no drift.

        `collect` also filters on `created_at__date` rather than comparing a
        `YYYY-MM-DD` string against an `auto_now_add` datetime, which is what
        made the final day of a range disappear.
        """
        dimension, column = None, TOTAL_KEY
        if customer_uid := request.query_params.get("customer_uid"):
            dimension, column = "customer", customer_uid
        elif warehouse_uid := request.query_params.get("warehouse_uid"):
            dimension, column = "warehouse", warehouse_uid

        cells, accounts, _labels = collect(
            request.user.get_active_company(),
            request.query_params.get("start_date"),
            request.query_params.get("end_date"),
            dimension=dimension,
        )
        amounts = {
            uid: cells.get((column, uid), Decimal("0.00")) for uid in accounts
        }
        return amounts, accounts

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        amounts, accounts = self.period_amounts(request)
        # Read by get_serializer_context, so every row rendered below reports
        # the same period this response's totals were computed over.
        self._period_amounts = {uid: amount for uid, amount in amounts.items()}

        by_section = defaultdict(lambda: Decimal("0.00"))
        for uid, account in accounts.items():
            by_section[account["section"]] += amounts[uid]

        data = {
            "total_income": by_section[INCOME],
            "total_cost_of_goods": by_section[COGS],
            # `_section_of` carves payroll out of EXPENSES; the figure this
            # replaces did not, so both sections sum here to keep the total
            # meaning what it meant.
            "total_expenses": by_section[EXPENSES] + by_section[PAYROLL_EXPENSES],
            "total_other_expenses": by_section[OTHER_EXPENSES],
            "total_other_income": by_section[OTHER_INCOME],
        }
        total_income = data["total_income"] or 0
        total_cost_of_goods = data["total_cost_of_goods"] or 0

        # Total gross profit
        total_gross_profit = data["total_gross_profit"] = (
            total_income - total_cost_of_goods
        ) or 0

        total_expenses = data["total_expenses"] or 0
        total_other_expenses = data["total_other_expenses"] or 0

        # Total operating income
        total_net_operating_income = data["total_net_operating_income"] = (
            total_gross_profit - total_expenses
        ) or 0
        total_other_income = data["total_other_income"] or 0

        # Total net other income
        total_net_other_income = data["total_net_other_income"] = (
            total_other_income - total_other_expenses
        )

        # Total net income
        data["total_net_income"] = total_net_operating_income + total_net_other_income
        if request.query_params.get("keywords", None) == "overview":
            return Response(data)
        elif request.query_params.get("is_pdf", None) == "true":
            # Creating PDF
            pdf = get_pdf(
                self,
                True,
                {
                    "overview": data,
                    "data": {
                        "income_accounts": self.get_serializer(
                            queryset.filter(
                                Q(kind=ChartOfAccountKindChoices.INCOMES)
                                & (~Q(account_type__title="Other Income"))
                            ),
                            many=True,
                        ).data,
                        "cost_of_good_sold_accounts": self.get_serializer(
                            queryset.filter(
                                account_type__title="Cost of Goods Sold (COGS)"
                            ),
                            many=True,
                        ).data,
                        "expense_accounts": self.get_serializer(
                            self.get_expense_accounts(queryset), many=True
                        ).data,
                        "other_income_accounts": self.get_serializer(
                            queryset.filter(account_type__title="Other Income"),
                            many=True,
                        ).data,
                        "other_expense_accounts": self.get_serializer(
                            queryset.filter(account_type__title="Other Expenses"),
                            many=True,
                        ).data,
                    },
                    "label": "profit_loss",
                    "template": "reports/profit_loss.html",
                    "title": "Profit And Loss Report",
                    "is_report": True,
                },
            )
            return Response(
                {
                    "file_uid": pdf.uid,
                    "url": pdf.file.url,
                }
            )
        else:
            return super().list(request, *args, **kwargs)
