"""Custom summary report.

The spec offered two scopes and leaned towards the narrow one: a real report
*builder* (metric picker, group-by picker) needs UI that does not exist yet, so
this ships **Option B** -- one metric summarised by one dimension, which is
what the reference screenshot actually shows.

It is not a duplicate of the by-customer pivot, though: this reads any single
row of the P&L ladder, not just net income, and returns it as a flat two-column
table. That makes it a genuine (if small) builder rather than a subset, and
adding more metrics later is a matter of naming more ladder rows.
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
)


# Which ladder row each metric reads. Anything in the ladder can be exposed
# here; these are the ones worth naming today.
METRICS = {
    "net_income": "net_income",
    "gross_profit": "gross_profit",
    "net_operating_income": "net_operating_income",
    "income": "income.subtotal",
    "expenses": "expenses.subtotal",
}

GROUP_BY = {"customer": "customer", "store": "warehouse"}


class CustomSummaryReportView(AccountingReportView):
    report_title = "my custom summary report"
    pdf_template = "reports/custom_summary_report.html"
    pdf_filename = "custom_summary_report.pdf"

    def build_report(self, request, company):
        metric = request.query_params.get("metric", "net_income")
        group_by = request.query_params.get("group_by", "customer")
        if metric not in METRICS:
            raise ValueError(f"metric (expected one of {', '.join(sorted(METRICS))})")
        if group_by not in GROUP_BY:
            raise ValueError(
                f"group_by (expected one of {', '.join(sorted(GROUP_BY))})"
            )

        date_from, date_to = self.resolve_range(request)
        cells, accounts, labels = collect(
            company, date_from, date_to, dimension=GROUP_BY[group_by]
        )
        columns = pivot_columns(labels, cells)
        add_total_column(cells, [column["key"] for column in columns])
        ladder = build_ladder(
            [column["key"] for column in columns], cells, accounts
        )

        row = next((r for r in ladder if r["key"] == METRICS[metric]), None)
        values = (row or {}).get("values", {})

        return {
            "title": request.query_params.get("title") or self.report_title,
            "subtitle": format_span(date_from, date_to),
            "metric": metric,
            "group_by": group_by,
            "rows": [
                {
                    "key": column["key"],
                    "label": column["label"],
                    "value": values.get(column["key"], "0.00"),
                }
                for column in columns
                if not column["is_total"]
            ],
            "total": values.get(TOTAL_KEY, "0.00"),
        }
