"""Build the "Income by Customer Summary" report.

Three figures per customer for a period -- income, expenses, net income -- with
sub-customers nested under their parent and a "Total for <parent>" line, then a
grand TOTAL.

This is `profit_loss_engine.collect` on the customer dimension, with the full
profit-and-loss ladder collapsed to two buckets: everything that increases
profit and everything that reduces it. So it agrees with Profit & Loss by
Customer by construction -- this report's Net income column is that report's
Net Income row, one column per customer.

**Expenses print negative.** The engine returns every section positive within
itself (an expense of 100 is +100); the reference prints expenses as -100 and
reads Net income as Income + Expenses. The negation happens here, at the
presentation edge, so the engine's convention stays the one thing every report
shares.

⚠️ Only income and cost of goods sold are actually attributable to a customer
today -- no purchase, bill, expense or cheque posting carries a customer, so
those land in "Not specified". The Expenses column is therefore a
cost-of-sales figure for named customers, not their full cost. See
`frontend-companion/SALES_REPORTS.md` and the by-customer profit-and-loss doc.
"""

from collections import defaultdict
from decimal import Decimal

from weapi.django_rest.helpers.reports.customer_tree import (
    customer_tree,
    tree_rows,
)
from weapi.django_rest.helpers.reports.profit_loss_engine import (
    COGS,
    EXPENSES,
    INCOME,
    OTHER_EXPENSES,
    OTHER_INCOME,
    PAYROLL_EXPENSES,
    UNASSIGNED_KEY,
    UNASSIGNED_LABEL,
    amount_string,
    collect,
)


ZERO = Decimal("0.00")

INCOME_SECTIONS = (INCOME, OTHER_INCOME)
EXPENSE_SECTIONS = (COGS, EXPENSES, PAYROLL_EXPENSES, OTHER_EXPENSES)

COLUMNS = [
    {"key": "name", "label": "", "align": "left"},
    {"key": "income", "label": "Income", "align": "right"},
    {"key": "expenses", "label": "Expenses", "align": "right"},
    {"key": "net_income", "label": "Net income", "align": "right"},
]


def _negate(value):
    """`-value`, but zero stays unsigned.

    `-Decimal("0.00")` is `Decimal("-0.00")` and formats as `-0.00`; the
    reference prints a customer with no costs as a plain `0.00`.
    """
    return -value if value else ZERO


class Figures:
    """Income and expenses for one customer, both held positive."""

    def __init__(self):
        self.income = ZERO
        self.expenses = ZERO

    def add(self, other):
        self.income += other.income
        self.expenses += other.expenses
        return self

    def cells(self):
        """The three printed amounts, expenses negated for display."""
        return {
            "income": amount_string(self.income),
            "expenses": amount_string(_negate(self.expenses)),
            "net_income": amount_string(self.income - self.expenses),
        }


def _totals_by_customer(cells, accounts):
    """Per-customer income/expense totals from the engine's (key, account) cells."""
    section_of = {uid: account["section"] for uid, account in accounts.items()}
    totals = defaultdict(Figures)
    for (customer_key, account_uid), amount in cells.items():
        section = section_of.get(account_uid)
        if section in INCOME_SECTIONS:
            totals[customer_key].income += amount
        elif section in EXPENSE_SECTIONS:
            totals[customer_key].expenses += amount
    return totals


def build_income_by_customer(company, date_from=None, date_to=None):
    """One row per customer -- income, expenses, net income -- then a TOTAL."""
    cells, accounts, labels = collect(
        company, date_from, date_to, dimension="customer"
    )
    totals = _totals_by_customer(cells, accounts)

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
                    **totals[key].cells(),
                }
            )
            continue
        subtotal = Figures()
        for member in subtree:
            subtotal.add(totals[member])
        rows.append(
            {
                "key": f"{key}.total",
                "label": f"Total for {names.get(key, '')}",
                "depth": depth,
                "customer_uid": None,
                "is_total": True,
                **subtotal.cells(),
            }
        )

    # Summed over every customer rather than by accumulating the subtotals
    # above, so the grand total stays right even if the hierarchy is malformed.
    grand = Figures()
    for figures in totals.values():
        grand.add(figures)
    rows.append(
        {
            "key": "total",
            "label": "TOTAL",
            "depth": 0,
            "customer_uid": None,
            "is_total": True,
            **grand.cells(),
        }
    )
    return {"columns": COLUMNS, "rows": rows}
