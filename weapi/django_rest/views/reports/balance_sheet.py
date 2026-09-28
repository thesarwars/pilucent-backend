from decimal import Decimal

from collections import defaultdict

from datetime import datetime

import tempfile, weasyprint

from django_filters.rest_framework import DjangoFilterBackend

from django.utils.dateparse import parse_date
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.template.loader import render_to_string

from rest_framework import status, response, generics, filters
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

from journalio.models import JournalEntryConnector

from weapi.django_rest.helpers.reports.account_activity import (
    has_journal_line,
    with_journal_activity,
)
from weapi.django_rest.helpers.reports.net_income import (
    net_income_from_balances,
)

from ...serializers.reports.balance_sheet import (
    BalanceSheetDetailsSerializer,
    BalanceSheetFilter,
    PrivateWeBalanceSheetSummarySerializer,
    PrivateWeBalanceSheetListSerializer,
)


class BalanceSheetDetailsView(generics.ListAPIView):
    """
    API view to retrieve the details of a balance sheet.
    """

    # queryset = JournalEntryConnector.objects.all()
    # queryset = JournalEntryConnector.objects.select_related(
    #     'account',
    #     'journal',
    #     'supplier',
    #     'customer',
    #     'warehose',
    #     'tax',
    #     'created_by'
    # ).filter()
    queryset = JournalEntryConnector.objects.select_related(
        "account", "journal", "supplier", "customer", "warehose", "tax", "created_by"
    ).filter()
    serializer_class = BalanceSheetDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filterset_class = BalanceSheetFilter
    filter_backends = [DjangoFilterBackend]
    # lookup_field = "uid"

    def get_queryset(self):
        """Company-scoped, always.

        The class attribute above is `JournalEntryConnector.objects...filter()`
        with no arguments -- every tenant's journal lines. `account__company`
        was applied only inside the date-ranged branch of `list()`, so a request
        that omitted `created_at_after`/`created_at_before` returned all of
        them. And `list()` never calls `filter_queryset`, so the filterset could
        not have narrowed it either.

        Third instance of this exact shape. `12d0ea30` fixed the journal report
        and the general ledger, both of which likewise had the company filter
        nested inside a date-range branch. Scoping the queryset rather than the
        branch is what stops a fourth.

        `get_active_company()` returning None yields no rows, which is the right
        way to fail.
        """
        return self.queryset.filter(
            account__company=self.request.user.get_active_company()
        )

    def list(self, request, *args, **kwargs):
        start_date_param = request.query_params.get("created_at_after")
        end_date_param = request.query_params.get("created_at_before")
        start_date = parse_date(start_date_param) if start_date_param else None
        end_date = parse_date(end_date_param) if end_date_param else None
        is_pdf = request.query_params.get("is_pdf")

        company_rows = self.get_queryset()
        qs = (
            company_rows.filter(
                created_at__date__range=(start_date, end_date),
            ).order_by("created_at")
            if start_date and end_date
            # Ordered either way: a running balance is only meaningful if the
            # rows accumulate in the order they happened.
            else company_rows.order_by("created_at")
        )

        opening_balances = self.calculate_opening_balance(start_date)
        serializer = self.serializer_class(qs, many=True)
        grouped_data = {}
        valid_heads = {"ASSETS", "LIABILITIES", "EQUITIES"}
        # Running balance per account, accumulated from its opening figure.
        # `JournalEntryConnector.last_balance` is a stored snapshot and has
        # drifted from the journal on real data, so a ledger that printed it
        # per row did not agree with its own opening balance or its own
        # movements. Recomputing here makes the column add up by construction.
        running = {}

        for item in serializer.data:
            account_head = item.pop("co_account_head")
            if account_head not in valid_heads:
                continue
            account_name = item.pop("co_account")
            created_at_value = item.pop("created_at", None)
            created_at = (
                datetime.fromisoformat(created_at_value).date().isoformat()
                if created_at_value
                else None
            )
            amount = item.get("amount", 0.0)
            entry_data = {
                key: value
                for key, value in item.items()
                if key not in ["co_account", "co_account_head", "created_at"]
            }

            # making nested KeyValue pair

            # if account_head not in grouped_data:
            #     grouped_data[account_head] = {}

            # if account_name not in grouped_data[account_head]:
            #     grouped_data[account_head][account_name] = {}

            # if created_at not in grouped_data[account_head][account_name]:
            #     grouped_data[account_head][account_name][created_at] = []
            head_data = grouped_data.setdefault(
                account_head,
                {
                    f"total for {account_head}": 0.0,
                },
            )

            account_data = head_data.setdefault(
                account_name,
                {
                    "beginning_balance": opening_balances.get(account_name, 0.0),
                    f"total for {account_name}": 0.0,
                },
            )
            account_data[f"total for {account_name}"] += amount

            head_data[f"total for {account_head}"] += amount

            if account_name not in running:
                running[account_name] = Decimal(
                    str(opening_balances.get(account_name, 0))
                )
            running[account_name] += Decimal(str(amount))
            # Both keys carry the recomputed figure: `running_balance` is the
            # honest name, and `last_balance` is overwritten because the ledger
            # must not display a stored value it has just contradicted.
            entry_data["running_balance"] = f"{running[account_name]:.3f}"
            entry_data["last_balance"] = entry_data["running_balance"]

            account_data.setdefault(created_at, []).append(entry_data)
        if is_pdf == "true":
            return self.render_to_pdf(
                grouped_data,
                start_date,
                end_date,
                self.request.user.get_active_company(),
            )
        return response.Response(grouped_data, status=status.HTTP_200_OK)

    def render_to_pdf(self, grouped_data, start_date, end_date, company):
        """
        Calculate the total amount for each account in the given data.
        """
        html_string = render_to_string(
            "reports/balance_sheet_temp.html",
            {
                "data": grouped_data,
                "start_date": start_date,
                "end_date": end_date,
                "company": company,
            },
        )
        with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as temp_pdf:
            weasyprint.HTML(string=html_string).write_pdf(temp_pdf.name)

            with open(temp_pdf.name, "rb") as pdf_file:
                pdf_content = pdf_file.read()
        response_pdf = HttpResponse(pdf_content, content_type="application/pdf")
        response_pdf["Content-Disposition"] = "inline; filename=balance_sheet_temp.pdf"
        return response_pdf

    def calculate_opening_balance(self, start_date):
        """Each account's balance immediately before `start_date`.

        This used to walk every prior line with no ordering and keep whichever
        `last_balance` it happened to see last, so the figure was whatever row
        the database returned last -- not the balance before the period, and not
        even stable between identical requests. On production City Bank opened
        at 100,001,919.00 against a true 100,020,898.75, and the ledger appeared
        to jump upward on a row that took money out.

        Summed from the lines rather than read off `last_balance`: that stored
        running balance has drifted from the journal on real data (see
        `manage.py audit_ledger`), so recomputing is the durable answer.

        Signed the way `BalanceSheetDetailsSerializer` signs each row -- positive
        in the account's natural direction -- so the opening figure and the
        movements below it agree.
        """
        balances = {}
        if not start_date:
            return balances

        rows = (
            JournalEntryConnector.objects.filter(
                account__company=self.request.user.get_active_company(),
                created_at__date__lt=start_date,
            )
            .values("account__title", "account__kind")
            .annotate(
                debit_total=Coalesce(Sum("debit"), Decimal("0.00")),
                credit_total=Coalesce(Sum("credit"), Decimal("0.00")),
            )
        )

        for row in rows:
            debit = Decimal(row["debit_total"] or 0)
            credit = Decimal(row["credit_total"] or 0)
            amount = (
                debit - credit
                if row["account__kind"]
                in (
                    ChartOfAccountKindChoices.ASSETS,
                    ChartOfAccountKindChoices.EXPENSES,
                )
                else credit - debit
            )
            # Grouped by title because the response itself is keyed by title.
            # Two accounts sharing one now add together rather than one
            # silently overwriting the other.
            title = row["account__title"]
            balances[title] = balances.get(title, Decimal("0.00")) + amount

        return balances

    # def list(self, request, *args, **kwargs):
    #     # qs = JournalEntryConnector.objects.select_related('account').all()
    #     serializer = self.serializer_class(self.queryset.all(), many=True)
    #     grouped_data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    #     for item in serializer.data:
    #         kind = item.pop('co_account_head')
    #         title = item.pop('co_account')
    #         created_at = datetime.fromisoformat(item.pop('created_at')).date().isoformat()
    #         grouped_data[kind][title][created_at].append(item)

    #     return response.Response([{kind: accounts} for kind, accounts in grouped_data.items()])


class PrivateWeBalanceSheetSummaryView(ListAPIView):
    serializer_class = PrivateWeBalanceSheetListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    pagination_class = None
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
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        # `with_journal_activity` instead of a join + .distinct(): chaining the
        # date filter below onto the same relation used to build a second join,
        # turning this into an accounts x lines x lines scan. Measured 8.37s
        # against 0.04s for identical output.
        queryset = with_journal_activity(
            ChartOfAccount.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                kind__in=[
                    ChartOfAccountKindChoices.ASSETS,
                    ChartOfAccountKindChoices.EQUITIES,
                    ChartOfAccountKindChoices.LIABILITIES,
                ],
            ),
            start_date,
            end_date,
        )
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        data = queryset.aggregate(
            total_for_bank_accounts=Coalesce(
                Sum("opening_balance", filter=Q(account_type__title="Bank")),
                Decimal("0.00"),
            ),
            total_for_account_receivables=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Accounts Receivable (A/R)"),
                ),
                Decimal("0.00"),
            ),
            total_for_other_current_assets=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Current Assets"),
                ),
                Decimal("0.00"),
            ),
            total_for_fixed_assets=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Fixed Assets"),
                ),
                Decimal("0.00"),
            ),
            total_for_other_assets=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Assets"),
                ),
                Decimal("0.00"),
            ),
            total_for_account_payables=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Accounts Payable (A/P)"),
                ),
                Decimal("0.00"),
            ),
            total_for_credit_cards=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Credit Cards"),
                ),
                Decimal("0.00"),
            ),
            # Split out so this view returns the same key set as the main
            # balance-sheet endpoint; a client rendering both no longer has to
            # special-case the shape. The pairing is anchored on account_type
            # for the reason given on the main view's copy.
            total_for_payroll_liabilities=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Current Liabilities")
                    & Q(detail_type__title="Payroll Liabilities"),
                ),
                Decimal("0.00"),
            ),
            total_for_other_current_liabilities=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Current Liabilities")
                    & (~Q(detail_type__title="Payroll Liabilities")),
                ),
                Decimal("0.00"),
            ),
            total_for_long_term_liabilities=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Long Term Liabilities"),
                ),
                Decimal("0.00"),
            ),
            total_for_equity=Coalesce(
                Sum(
                    "opening_balance",
                    # By kind, not by account_type title. account_type is a
                    # nullable FK with no validation, so the title test both
                    # dropped equity accounts whose type was never set and
                    # counted any non-equity account somebody typed "Equity".
                    # Matches how /summary-list already computes it.
                    filter=Q(kind=ChartOfAccountKindChoices.EQUITIES),
                ),
                Decimal("0.00"),
            ),
        )

        # Total for current assets
        data["total_for_current_asset"] = (
            data["total_for_bank_accounts"]
            + data["total_for_account_receivables"]
            + data["total_for_other_current_assets"]
        )

        # Total for assets
        data["total_for_assets"] = (
            data["total_for_current_asset"]
            + data["total_for_fixed_assets"]
            + data["total_for_other_assets"]
        )

        # Total for current liabilities. Payables and credit cards were
        # aggregated above and never reached this total; payroll liabilities
        # are now their own term, with other-current excluding them so each
        # account is counted once.
        data["total_for_current_liabilities"] = (
            data["total_for_account_payables"]
            + data["total_for_credit_cards"]
            + data["total_for_other_current_liabilities"]
            + data["total_for_payroll_liabilities"]
        )

        # Total for liabilities
        data["total_for_liabilities"] = (
            data["total_for_current_liabilities"]
            + data["total_for_long_term_liabilities"]
        )

        # Current-period net income belongs in equity -- without it the sheet
        # cannot balance, because assets are financed by liabilities plus
        # equity plus what the business earned. This queryset only ever sees
        # ASSETS/EQUITIES/LIABILITIES accounts, so it is computed separately.
        # `total_for_equity` keeps its existing meaning (equity accounts only);
        # render Net Income as its own line inside the Equity section.
        data["total_for_net_income"] = net_income_from_balances(
            self.request.user.get_active_company(),
            request.query_params.get("start_date"),
            request.query_params.get("end_date"),
        )

        # Total for liabilities and equity
        data["total_for_liabilities_and_equity"] = (
            data["total_for_equity"]
            + data["total_for_net_income"]
            + data["total_for_liabilities"]
        )

        if request.query_params.get("keywords", None) == "overview":
            return Response(data)
        else:
            return super().list(request, *args, **kwargs)


class PrivateWeBalanceSheetSummaryList(ListAPIView):
    serializer_class = PrivateWeBalanceSheetSummarySerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    pagination_class = None  # Disable pagination
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
        # Exists rather than a join + .distinct(): list() chains a second
        # filter on the same relation for the date range, which Django builds
        # as another join.
        return (
            ChartOfAccount.objects.get_status_all()
            .filter(company=self.request.user.get_active_company())
            .prefetch_related("journalentryconnector_set")
            .filter(has_journal_line())
        )

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()

        start_date = request.query_params.get("date_from", None)
        end_date = request.query_params.get("date_to", None)

        # Same conditions, expressed on the subquery so no second join appears.
        # Note these filter the journal's own date, not the connector's
        # created_at that the other balance-sheet views use.
        line_filters = {}
        if start_date:
            line_filters["journal__date__gte"] = start_date
        if end_date:
            line_filters["journal__date__lte"] = end_date

        query_base = self.get_queryset()
        if line_filters:
            query_base = query_base.filter(has_journal_line(**line_filters))

        bank_accounts = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.ASSETS, account_type__title="Bank"
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        accounts_receivable = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.ASSETS,
                # Seeded title carries the suffix; "Accounts Receivable"
                # alone is a detail type, so this matched nothing.
                account_type__title="Accounts Receivable (A/R)",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        other_current_assets = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.ASSETS,
                account_type__title="Other Current Assets",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        fixed_assets = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.ASSETS,
                account_type__title="Fixed Assets",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        other_assets = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.ASSETS,
                account_type__title="Other Assets",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        accounts_payable = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.LIABILITIES,
                account_type__title="Accounts Payable (A/P)",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        credit_cards = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.LIABILITIES,
                account_type__title="Credit Cards",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        other_current_liabilities = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.LIABILITIES,
                account_type__title="Other Current Liabilities",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        long_term_liabilities = (
            query_base.filter(
                kind=ChartOfAccountKindChoices.LIABILITIES,
                account_type__title="Long Term Liabilities",
            ).aggregate(total=Sum("opening_balance"))["total"]
            or 0
        )

        equity = (
            query_base.filter(kind=ChartOfAccountKindChoices.EQUITIES).aggregate(
                total=Sum("opening_balance")
            )["total"]
            or 0
        )

        # Calculate totals
        total_current_assets = (
            bank_accounts + accounts_receivable + other_current_assets
        )
        total_assets = total_current_assets + fixed_assets + other_assets

        total_current_liabilities = (
            accounts_payable + credit_cards + other_current_liabilities
        )
        total_liabilities = total_current_liabilities + long_term_liabilities

        net_income = net_income_from_balances(
            self.request.user.get_active_company(),
            request.query_params.get("start_date"),
            request.query_params.get("end_date"),
        )
        total_liabilities_and_equity = total_liabilities + equity + net_income

        # Structure the response to match the balance sheet format
        data = {
            "assets": {
                "current_assets": {
                    "bank_accounts": bank_accounts,
                    "accounts_receivable": accounts_receivable,
                    "other_current_assets": other_current_assets,
                    "total_for_current_assets": total_current_assets,
                },
                "fixed_assets": fixed_assets,
                "other_assets": other_assets,
                "total_for_assets": total_assets,
            },
            "liabilities_and_equity": {
                "liabilities": {
                    "current_liabilities": {
                        "accounts_payable": accounts_payable,
                        "credit_cards": credit_cards,
                        "other_current_liabilities": other_current_liabilities,
                        "total_for_current_liabilities": total_current_liabilities,
                    },
                    "long_term_liabilities": long_term_liabilities,
                    "total_for_liabilities": total_liabilities,
                },
                "equity": equity,
                "net_income": net_income,
                "total_for_liabilities_and_equity": total_liabilities_and_equity,
            },
        }

        if request.query_params.get("keywords", None) == "overview":
            return Response(data)
        else:
            return super().list(request, *args, **kwargs)


class PrivateWeBalanceSheetView(ListAPIView):
    serializer_class = PrivateWeBalanceSheetListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    pagination_class = None
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
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        # `with_journal_activity` instead of a join + .distinct(): chaining the
        # date filter below onto the same relation used to build a second join,
        # turning this into an accounts x lines x lines scan. Measured 8.37s
        # against 0.04s for identical output.
        queryset = with_journal_activity(
            ChartOfAccount.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                kind__in=[
                    ChartOfAccountKindChoices.ASSETS,
                    ChartOfAccountKindChoices.EQUITIES,
                    ChartOfAccountKindChoices.LIABILITIES,
                ],
            ),
            start_date,
            end_date,
        )
        if (
            self.request.query_params.get("account_type__title", None)
            == "Other Current Liabilities"
        ):
            queryset = queryset.filter(
                Q(account_type__title="Other Current Liabilities")
                & (~Q(detail_type__title="Payroll Liabilities"))
            )

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        data = queryset.aggregate(
            total_for_bank_accounts=Coalesce(
                Sum("opening_balance", filter=Q(account_type__title="Bank")),
                Decimal("0.00"),
            ),
            total_for_account_receivables=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Accounts Receivable (A/R)"),
                ),
                Decimal("0.00"),
            ),
            total_for_other_current_assets=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Current Assets"),
                ),
                Decimal("0.00"),
            ),
            total_for_fixed_assets=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Fixed Assets"),
                ),
                Decimal("0.00"),
            ),
            total_for_other_assets=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Assets"),
                ),
                Decimal("0.00"),
            ),
            total_for_account_payables=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Accounts Payable (A/P)"),
                ),
                Decimal("0.00"),
            ),
            total_for_credit_cards=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Credit Cards"),
                ),
                Decimal("0.00"),
            ),
            total_for_payroll_liabilities=Coalesce(
                Sum(
                    "opening_balance",
                    # Anchored on the account_type as well as the detail type.
                    # detail_type is an independent nullable FK with no
                    # parent validation, so on the detail type alone this also
                    # caught any A/P, credit-card, long-term-liability or even
                    # ASSET account someone tagged "Payroll Liabilities" --
                    # counting it in two totals at once. Same pairing as
                    # helpers/reports/balance_sheet_engine.py.
                    filter=Q(account_type__title="Other Current Liabilities")
                    & Q(detail_type__title="Payroll Liabilities"),
                ),
                Decimal("0.00"),
            ),
            total_for_other_current_liabilities=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Other Current Liabilities")
                    & (~Q(detail_type__title="Payroll Liabilities")),
                ),
                Decimal("0.00"),
            ),
            total_for_long_term_liabilities=Coalesce(
                Sum(
                    "opening_balance",
                    filter=Q(account_type__title="Long Term Liabilities"),
                ),
                Decimal("0.00"),
            ),
            total_for_equity=Coalesce(
                Sum(
                    "opening_balance",
                    # By kind, not by account_type title. account_type is a
                    # nullable FK with no validation, so the title test both
                    # dropped equity accounts whose type was never set and
                    # counted any non-equity account somebody typed "Equity".
                    # Matches how /summary-list already computes it.
                    filter=Q(kind=ChartOfAccountKindChoices.EQUITIES),
                ),
                Decimal("0.00"),
            ),
        )

        # Total for current assets
        data["total_for_current_asset"] = (
            data["total_for_bank_accounts"]
            + data["total_for_account_receivables"]
            + data["total_for_other_current_assets"]
        )

        # Total for assets
        data["total_for_assets"] = (
            data["total_for_current_asset"]
            + data["total_for_fixed_assets"]
            + data["total_for_other_assets"]
        )

        # Total for current liabilities.
        # Accounts payable and credit cards are aggregated above but were being
        # left out of this sum, so both vanished from Total for Liabilities and
        # the sheet could not balance.
        data["total_for_current_liabilities"] = (
            data["total_for_account_payables"]
            + data["total_for_credit_cards"]
            + data["total_for_other_current_liabilities"]
            + data["total_for_payroll_liabilities"]
        )

        # Total for liabilities
        data["total_for_liabilities"] = (
            data["total_for_current_liabilities"]
            + data["total_for_long_term_liabilities"]
        )

        # Current-period net income belongs in equity -- without it the sheet
        # cannot balance, because assets are financed by liabilities plus
        # equity plus what the business earned. This queryset only ever sees
        # ASSETS/EQUITIES/LIABILITIES accounts, so it is computed separately.
        # `total_for_equity` keeps its existing meaning (equity accounts only);
        # render Net Income as its own line inside the Equity section.
        data["total_for_net_income"] = net_income_from_balances(
            self.request.user.get_active_company(),
            request.query_params.get("start_date"),
            request.query_params.get("end_date"),
        )

        # Total for liabilities and equity
        data["total_for_liabilities_and_equity"] = (
            data["total_for_equity"]
            + data["total_for_net_income"]
            + data["total_for_liabilities"]
        )

        if request.query_params.get("keywords", None) == "overview":
            return Response(data)
        else:
            return super().list(request, *args, **kwargs)
