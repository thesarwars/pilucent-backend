import calendar
from datetime import date, datetime, timedelta

from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from rest_framework.generics import ListAPIView
from rest_framework.views import APIView

from rest_framework.response import Response

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountKindChoices

from weapi.django_rest.serializers.dashboards.v1.dashboards import (
    PrivateWeDashboardFinanceOverviewSerializer,
    PrivateWeDashboardBankOverviewSerializer,
)


class PrivateWeDashboardProfitLossOverview(APIView):
    ALLOWED_MONTH_WINDOWS = frozenset((3, 7, 12))

    def get_response_data(self, filters):
        response_data = (
            ChartOfAccount.objects.get_status_all()
            .filter(filters)
            .distinct()
            .aggregate(
                total_income=Coalesce(
                    Sum(
                        "opening_balance",
                        filter=Q(kind=ChartOfAccountKindChoices.INCOMES)
                        & (~Q(account_type__title="Other Income")),
                    ),
                    Decimal("0.00"),
                ),
                total_expense=Coalesce(
                    Sum(
                        "opening_balance",
                        filter=Q(kind=ChartOfAccountKindChoices.EXPENSES)
                        & Q(account_type__title="Cost of Goods Sold (COGS)"),
                    ),
                    Decimal("0.00"),
                ),
            )
        )
        return response_data

    def iter_month_starts(self, today, month_count):
        end_month_start = date(today.year, today.month, 1)
        start_month = end_month_start - relativedelta(months=month_count - 1)
        cursor = start_month
        while cursor <= end_month_start:
            yield cursor
            cursor = cursor + relativedelta(months=1)

    def get(self, request):
        user = request.user
        company = user.get_active_company()

        months_param = request.query_params.get("months", "12")
        try:
            month_count = int(months_param)
        except (TypeError, ValueError):
            month_count = 12
        if month_count not in self.ALLOWED_MONTH_WINDOWS:
            month_count = 12

        base_filters = Q(
            company=company,
            journalentryconnector__isnull=False,
        )

        today = date.today()
        data = []
        for month_start in self.iter_month_starts(today, month_count):
            month_filters = base_filters & Q(
                journalentryconnector__created_at__year=month_start.year,
                journalentryconnector__created_at__month=month_start.month,
            )
            totals = self.get_response_data(month_filters)
            data.append(
                {
                    "month": calendar.month_abbr[month_start.month],
                    "profit": totals["total_income"],
                    "loss": totals["total_expense"],
                }
            )

        return Response({"data": data}, 200)


class PrivateWeDashboardBankOverview(ListAPIView):
    ALLOWED_MONTH_WINDOWS = frozenset((3, 7, 12))
    serializer_class = PrivateWeDashboardBankOverviewSerializer

    def iter_month_starts(self, today, month_count):
        end_month_start = date(today.year, today.month, 1)
        start_month = end_month_start - relativedelta(months=month_count - 1)
        cursor = start_month
        while cursor <= end_month_start:
            yield cursor
            cursor = cursor + relativedelta(months=1)

    def get_chart_of_accounts(self):
        if not hasattr(self, "_chart_of_accounts"):
            self._chart_of_accounts = ChartOfAccount.objects.filter(
                account_type__title="Bank",
                company=self.request.user.get_active_company(),
                transactioninformation__isnull=False,
            ).distinct()
        return self._chart_of_accounts

    def get_queryset(self):
        return self.get_chart_of_accounts()[:4]

    def list(self, request, *args, **kwargs):
        response_data = super().list(request, *args, **kwargs)
        chart_of_accounts = self.get_chart_of_accounts()

        months_param = request.query_params.get("months", "12")
        try:
            month_count = int(months_param)
        except (TypeError, ValueError):
            month_count = 12
        if month_count not in self.ALLOWED_MONTH_WINDOWS:
            month_count = 12

        total_opening_balance = chart_of_accounts.aggregate(
            total=Coalesce(Sum("opening_balance"), Decimal("0.00"))
        )["total"]

        today = date.today()
        monthly_rows = []
        for month_start in self.iter_month_starts(today, month_count):
            month_total = chart_of_accounts.filter(
                transactioninformation__created_at__year=month_start.year,
                transactioninformation__created_at__month=month_start.month,
            ).aggregate(
                total=Coalesce(Sum("opening_balance"), Decimal("0.00"))
            )["total"]
            monthly_rows.append(
                {
                    "month": calendar.month_abbr[month_start.month],
                    "amount": float(month_total),
                }
            )

        response_data.data["count"] = len(chart_of_accounts)
        response_data.data["total"] = f"{total_opening_balance:.3f}"
        response_data.data["current_year"] = monthly_rows

        return response_data


class PrivateWeDashboardExpenseOverview(APIView):
    def get_response_data(self, filters):
        response_data = ChartOfAccount.objects.filter(filters).aggregate(
            total_cost_of_good=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(title="Cost of Goods Sold (COGS)"),
                ),
                Decimal("0.00"),
            ),
            total_other_miscellaneous=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(title="Other Miscellaneous Expense"),
                ),
                Decimal("0.00"),
            ),
            total_other_expenses=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Expenses"),
                ),
                Decimal("0.00"),
            ),
        )
        response_data["total"] = (
            response_data.get("total_cost_of_good")
            + response_data.get("total_other_miscellaneous")
            + response_data.get("total_other_expenses")
        )

        return response_data

    def get(self, request):
        user = request.user
        company = user.get_active_company()

        # Filters
        filters = Q(company=company, kind=ChartOfAccountKindChoices.EXPENSES)
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        last_30_days_ago_response_data = None
        if start_date and end_date:

            # last 30 days ago
            last_30_days_ago_date = datetime.strptime(
                start_date, "%Y-%m-%d"
            ).date() - timedelta(days=30)

            last_30_days_filters = filters & Q(
                journalentryconnector__created_at__range=[
                    last_30_days_ago_date,
                    start_date,
                ]
            )
            last_30_days_ago_response_data = self.get_response_data(
                last_30_days_filters
            )

            # Current
            filters = filters & Q(
                journalentryconnector__created_at__range=[start_date, end_date]
            )

        # Data
        response_data = self.get_response_data(filters)
        if last_30_days_ago_response_data:
            current_total = response_data["total"]
            last_30_days_ago_total = last_30_days_ago_response_data["total"]

            # Monthly growth calculation in percentage
            response_data["prior_month_growth"] = (
                ((current_total - last_30_days_ago_total) / last_30_days_ago_total)
                * 100
                if last_30_days_ago_total != 0
                else 0
            )
        return Response(response_data, 200)


class PrivateWeDashboardFinanceOverview(ListAPIView):
    serializer_class = PrivateWeDashboardFinanceOverviewSerializer

    def get_queryset(self):
        return ChartOfAccount.objects.filter(
            title__in=["Accounts Payable (A/P)", "Accounts Receivable (A/R)"],
            company=self.request.user.get_active_company(),
        )
