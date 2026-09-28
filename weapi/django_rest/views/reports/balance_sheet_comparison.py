"""The balance sheet as a hierarchy: one period, or two side by side.

Both shapes come from one view because a comparison *is* the single-period
report with a second column. Returning the whole tree in one response is the
point: the older `/balance-sheet` returns a flat list, so a screen has to
call it once per account category and reassemble the hierarchy itself --
eleven requests, joined on account *title* because a flat row carries no id.
Here every row already has its `account_uid`, `depth` and subtotals.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from rest_framework.response import Response

from common.django_rest.helpers.fiscal import fiscal_year_start

from weapi.django_rest.helpers.reports.balance_sheet_engine import (
    build_comparison_rows,
    collect_as_of,
)
from weapi.django_rest.helpers.reports.net_income import (
    net_income_from_journal,
)
from weapi.django_rest.views.reports.accounting_report_base import (
    AccountingReportView,
    shift_year,
)


class BalanceSheetComparisonView(AccountingReportView):
    report_title = "Balance sheet comparison report"
    pdf_template = "reports/balance_sheet_comparison.html"
    pdf_filename = "balance_sheet_comparison.pdf"

    # What to compare against when the caller names no second period.
    # `?compare_to=none` turns it off for a one-column report.
    default_compare = "previous_year"

    def build_report(self, request, company):
        _, as_of = self.resolve_range(request)
        _, compare_as_of = self.resolve_range(request, prefix="compare_")

        # Both param shapes the spec offered work: send the comparison date
        # explicitly, or let this own the "a year earlier" math. Explicit wins.
        if compare_as_of is None:
            compare_to = request.query_params.get("compare_to", self.default_compare)
            if compare_to == "previous_year":
                compare_as_of = shift_year(as_of)

        periods = [("current", as_of)]
        if compare_as_of:
            periods.append(("compare_1", compare_as_of))

        balances_by_column = {}
        net_income_by_column = {}
        retained_prior_by_column = {}
        accounts = {}
        columns = []
        for key, date_value in periods:
            balances, period_accounts = collect_as_of(company, date_value)
            balances_by_column[key] = balances

            # The fiscal boundary comes from the COLUMN's own as-of date, never
            # from today. Spec 5.1 requires that "comparative reports remain
            # reproducible", and deriving the boundary from today would restate
            # every historical column at each fiscal rollover -- a balance sheet
            # as of 2025-12-31 has to say the same thing next year as it does
            # now. With no as-of at all there is nothing to derive a boundary
            # from, so today stands in and the column discloses which date it
            # used.
            effective = date_value or timezone.localdate()
            fy_start = fiscal_year_start(company, effective)

            # Prior years is one unbounded query for everything dated at or
            # before the day the fiscal year opened; the current period is what
            # is left over. Deriving the second by SUBTRACTION rather than
            # querying it independently is the whole safety property -- see
            # build_comparison_rows for why a second range query would not be a
            # partition.
            cumulative = net_income_from_journal(company, date_value)
            prior = net_income_from_journal(
                company, fy_start - timedelta(days=1)
            ).quantize(Decimal("0.01"))

            retained_prior_by_column[key] = prior
            net_income_by_column[key] = cumulative - prior

            accounts.update(period_accounts)
            columns.append(
                {
                    "key": key,
                    "label": (
                        f"As of {date_value.strftime('%b %-d, %Y')}"
                        if date_value
                        else "All dates"
                    ),
                    "date_to": date_value,
                    "fy_start": fy_start,
                    "as_of_effective": effective,
                }
            )

        subtitle = columns[0]["label"]
        if len(columns) > 1:
            subtitle = f"{columns[0]['label']}, compared to {columns[1]['label']}"

        return {
            "subtitle": subtitle,
            "columns": columns,
            "rows": build_comparison_rows(
                [column["key"] for column in columns],
                balances_by_column,
                accounts,
                net_income_by_column=net_income_by_column,
                retained_prior_by_column=retained_prior_by_column,
            ),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        wanted = {"assets.total", "liabilities.total", "equity.total",
                  "total_for_liabilities_and_equity"}
        return Response(
            {
                row["key"]: row["values"]
                for row in report["rows"]
                if row["key"] in wanted
            }
        )


class BalanceSheetFullView(BalanceSheetComparisonView):
    """One period, whole hierarchy, one request.

    The replacement for calling `/balance-sheet` once per account category. Same
    rows as the comparison report with a single `current` column, so the two
    endpoints cannot drift apart.

    Note this reads the **journal**, while the older `/balance-sheet` sums
    `ChartOfAccount.opening_balance`. Where that stored running balance has
    drifted from the lines behind it the two disagree -- see `audit_ledger`.
    This one is the trustworthy figure.
    """

    report_title = "Balance sheet"
    pdf_filename = "balance_sheet.pdf"
    default_compare = None
