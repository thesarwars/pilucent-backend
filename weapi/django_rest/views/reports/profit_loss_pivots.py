"""Profit and loss pivoted by customer or by store, and the comparison report.

All three share `profit_loss_engine`: same ladder, same signs, different
columns. What differs is only what a column *is* -- a customer, a store, or a
period.
"""

from rest_framework.response import Response

from weapi.django_rest.helpers.reports.profit_loss_engine import (
    TOTAL_KEY,
    add_total_column,
    build_ladder,
    collect,
    pivot_columns,
)
from weapi.django_rest.views.reports.accounting_report_base import (
    AccountingReportView,
    format_span,
    shift_year,
)


class _ProfitLossPivotView(AccountingReportView):
    """One column per dimension instance, plus Not specified, plus Total."""

    dimension = None

    def build_report(self, request, company):
        date_from, date_to = self.resolve_range(request)
        cells, accounts, labels = collect(
            company, date_from, date_to, dimension=self.dimension
        )
        columns = pivot_columns(labels, cells)
        add_total_column(cells, [column["key"] for column in columns])

        return {
            "subtitle": format_span(date_from, date_to),
            "date_from": date_from,
            "date_to": date_to,
            "columns": columns,
            "rows": build_ladder(
                [column["key"] for column in columns], cells, accounts
            ),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        # The Total column is not a dimension instance.
        count = sum(1 for column in report["columns"] if not column["is_total"])
        return Response({self.overview_key: count})


class ProfitLossByCustomerView(_ProfitLossPivotView):
    report_title = "Profit and loss by customer report"
    pdf_template = "reports/profit_loss_pivot.html"
    pdf_filename = "profit_loss_by_customer.pdf"
    dimension = "customer"
    overview_key = "customer_count"


class ProfitLossByStoreView(_ProfitLossPivotView):
    report_title = "Profit and loss by store report"
    pdf_template = "reports/profit_loss_pivot.html"
    pdf_filename = "profit_loss_by_store.pdf"
    dimension = "warehouse"
    overview_key = "store_count"


class ProfitLossComparisonView(AccountingReportView):
    """One column per period.

    `columns` is a list rather than a fixed pair so a second comparison period
    can be added later without a shape change -- the spec asked for that
    explicitly.
    """

    report_title = "Profit and loss comparison report"
    pdf_template = "reports/profit_loss_pivot.html"
    pdf_filename = "profit_loss_comparison.pdf"

    def build_report(self, request, company):
        date_from, date_to = self.resolve_range(request)
        compare_from, compare_to = self.resolve_range(request, prefix="compare_")

        # Both param shapes the spec offered are supported: send the second
        # range explicitly, or name a relative period and let this own the
        # math. Explicit wins when both are present.
        if compare_from is None and compare_to is None:
            if request.query_params.get("compare_to", "previous_year") == "previous_year":
                compare_from = shift_year(date_from)
                compare_to = shift_year(date_to)

        periods = [("current", date_from, date_to)]
        if compare_from or compare_to:
            periods.append(("compare_1", compare_from, compare_to))

        cells = {}
        accounts = {}
        columns = []
        for key, period_from, period_to in periods:
            period_cells, period_accounts, _ = collect(
                company, period_from, period_to
            )
            for (_, account_uid), amount in period_cells.items():
                cells[(key, account_uid)] = amount
            accounts.update(period_accounts)
            columns.append(
                {
                    "key": key,
                    "label": format_span(period_from, period_to),
                    "date_from": period_from,
                    "date_to": period_to,
                }
            )

        subtitle = columns[0]["label"]
        if len(columns) > 1:
            subtitle = f"{columns[0]['label']} compared to {columns[1]['label']}"

        return {
            "subtitle": subtitle,
            "columns": columns,
            "rows": build_ladder(
                [column["key"] for column in columns], cells, accounts
            ),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        net_income = next(
            (row for row in report["rows"] if row["key"] == "net_income"), None
        )
        return Response({"net_income": net_income["values"] if net_income else {}})
