"""Build the "Sales by Customer Summary" report.

Income per customer for a period, with sub-customers nested under their parent
and a "Total for <parent>" line beneath them -- `Customer.parent` is a self-FK,
so the hierarchy is real rather than inferred from names.

Sales come from the journal via `profit_loss_engine.collect`, restricted to
income accounts. That is the same path the by-customer profit and loss uses, so
the two agree: this report is that report's income section, flattened to one
column.

A customer can total **negative** -- a credit note or refund outweighing sales in
the period. The reference report shows exactly that, so nothing is clamped.
"""

from collections import defaultdict
from decimal import Decimal

from weapi.django_rest.helpers.reports.customer_tree import (
    customer_tree,
    tree_rows,
)
from weapi.django_rest.helpers.reports.profit_loss_engine import (
    INCOME,
    OTHER_INCOME,
    UNASSIGNED_KEY,
    UNASSIGNED_LABEL,
    amount_string,
    collect,
)


ZERO = Decimal("0.00")

COLUMNS = [
    {"key": "name", "label": "", "align": "left"},
    {"key": "total", "label": "Total", "align": "right"},
]


def build_sales_by_customer(company, date_from=None, date_to=None):
    """One row per customer, sub-customers nested, then a TOTAL."""
    cells, accounts, labels = collect(
        company, date_from, date_to, dimension="customer"
    )

    # Sales only. Expense and cost-of-goods lines belong to other reports, and
    # including them would make a "sales" figure that is not sales.
    income_accounts = {
        account["uid"]
        for account in accounts.values()
        if account["section"] in (INCOME, OTHER_INCOME)
    }

    totals = defaultdict(lambda: ZERO)
    for (customer_key, account_uid), amount in cells.items():
        if account_uid in income_accounts:
            totals[customer_key] += amount

    parents, names = customer_tree(company, totals.keys())
    for key in totals:
        names.setdefault(
            key, UNASSIGNED_LABEL if key == UNASSIGNED_KEY else labels.get(key, "")
        )

    rows = []
    for key, depth, subtree in tree_rows(set(totals), parents, names):
        if subtree is None:
            rows.append(
                {
                    "key": key,
                    "label": names.get(key, ""),
                    "depth": depth,
                    "customer_uid": None if key == UNASSIGNED_KEY else key,
                    "is_total": False,
                    "total": amount_string(totals[key]),
                }
            )
            continue
        rows.append(
            {
                "key": f"{key}.total",
                "label": f"Total for {names.get(key, '')}",
                "depth": depth,
                "customer_uid": None,
                "is_total": True,
                "total": amount_string(sum(totals[m] for m in subtree)),
            }
        )

    # Summed over every customer rather than by accumulating the subtotals
    # above, so the grand total stays right even if the hierarchy is malformed.
    rows.append(
        {
            "key": "total",
            "label": "TOTAL",
            "depth": 0,
            "customer_uid": None,
            "is_total": True,
            "total": amount_string(sum(totals.values(), ZERO)),
        }
    )
    return {"columns": COLUMNS, "rows": rows}
