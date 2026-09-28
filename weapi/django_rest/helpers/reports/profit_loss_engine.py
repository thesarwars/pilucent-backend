"""Shared engine behind the profit-and-loss family of reports.

**This does not reuse the existing `/reports/profit-losses` aggregation, and
that is deliberate.** That view sums `ChartOfAccount.opening_balance` -- an
account's lifetime running balance -- and uses the journal only to decide
*which accounts* appear (`profit_loss_reports.py:78-103`). The consequences:

* the date range never scopes the **amount**, only the account list, so two
  different periods return the same figures for any account touched in both;
* its existing `customer_uid` / `warehouse_uid` filters are worse than useless
  for a pivot -- each column would show the whole-company balance of every
  account that ever touched that customer.

A per-customer, per-store or period-comparison report cannot be built on that.
So these reports aggregate `JournalEntryConnector.debit` / `.credit`, which is
where the dimensional attribution actually lives.

Sign convention follows `common.django_rest.helpers.balance_helpers`: income
increases on the credit side, expenses on the debit side. Both are returned
**positive within their own section**, matching how the printed reports read.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce

from accounts.choices import ChartOfAccountKindChoices
from journalio.models import JournalEntryConnector


ZERO = Decimal("0.00")

# These are `Category.title` strings, not enum members -- `account_type` and
# `detail_type` are FKs to `categoryio.Category`, whose titles come from the
# chart-of-accounts seed. The existing P&L hard-codes the same literals in six
# places; they are named once here.
COGS_TITLE = "Cost of Goods Sold (COGS)"
OTHER_INCOME_TITLE = "Other Income"
OTHER_EXPENSES_TITLE = "Other Expenses"

# Detail types that make an expense account a *payroll* expense. The seeds only
# ever use the first, but the other two exist as categories and one industry
# seed carries a singular typo, so all four are matched.
PAYROLL_EXPENSE_DETAIL_TITLES = (
    "Payroll Expenses",
    "Payroll Expense",
    "Payroll Tax Expenses",
    "Payroll Wage Expenses",
)

UNASSIGNED_KEY = "not_specified"
UNASSIGNED_LABEL = "Not specified"
TOTAL_KEY = "total"

# Section keys, in print order.
INCOME = "income"
COGS = "cost_of_goods_sold"
EXPENSES = "expenses"
PAYROLL_EXPENSES = "payroll_expenses"
OTHER_INCOME = "other_income"
OTHER_EXPENSES = "other_expenses"


def amount_string(value):
    return f"{Decimal(value or 0).quantize(Decimal('0.01')):.2f}"


def _signed_amount(kind):
    """Income nets credit-debit; expense nets debit-credit."""
    if kind == ChartOfAccountKindChoices.INCOMES:
        return F("credit") - F("debit")
    return F("debit") - F("credit")


def _section_of(account_kind, account_type_title, detail_type_title):
    """Which P&L section an account belongs to, or None if it is not a P&L account."""
    if account_type_title == COGS_TITLE:
        return COGS
    if account_kind == ChartOfAccountKindChoices.INCOMES:
        return OTHER_INCOME if account_type_title == OTHER_INCOME_TITLE else INCOME
    if account_kind == ChartOfAccountKindChoices.EXPENSES:
        if account_type_title == OTHER_EXPENSES_TITLE:
            return OTHER_EXPENSES
        if detail_type_title in PAYROLL_EXPENSE_DETAIL_TITLES:
            return PAYROLL_EXPENSES
        return EXPENSES
    return None


def collect(company, date_from, date_to, *, dimension=None):
    """Signed amounts per (dimension value, account) from the journal.

    `dimension` is None, `"customer"` or `"warehouse"`. Returns
    `(cells, accounts, dimension_labels)` where `cells` maps
    `(dimension key, account uid)` to a Decimal, `accounts` maps an account uid
    to its metadata, and `dimension_labels` maps a dimension key to its label.

    Dates filter on the leg's own `date` -- the date the transaction BELONGS
    to. They used to filter `created_at__date`, the day the row was typed, and
    that is what made a prior period keep moving: amending a March sale in
    September deletes its legs and reposts them with a September `created_at`,
    so March's revenue silently left the March P&L and never came back.

    Header-authoritative, decided 2026-09-02. `JournalEntry.date` is the truth
    and every leg inherits it -- `create_journal_entry_connector` has always
    defaulted the leg date to the entry's, and no writer sets one to anything
    else. Filtering the leg date therefore asks the same question as filtering
    the header, and does it against the `(account, date, id)` index rather than
    through a join.

    The `__date` half of the old comparison is still worth remembering: a
    `YYYY-MM-DD` string against an `auto_now_add` datetime silently drops the
    final day. A `DateField` has no such trap, which is one fewer thing to get
    wrong.
    """
    field = {"customer": "customer", "warehouse": "warehose"}.get(dimension)

    rows = JournalEntryConnector.objects.filter(
        journal__company=company,
        account__kind__in=[
            ChartOfAccountKindChoices.INCOMES,
            ChartOfAccountKindChoices.EXPENSES,
        ],
    ).exclude(account__status="REMOVED")

    if date_from:
        rows = rows.filter(date__gte=date_from)
    if date_to:
        rows = rows.filter(date__lte=date_to)

    values = [
        "account__uid",
        "account__title",
        "account__kind",
        "account__account_type__title",
        "account__detail_type__title",
    ]
    if field:
        values += [f"{field}__uid", f"{field}__title"]
        if dimension == "customer":
            values += [f"{field}__display_name", f"{field}__first_name",
                       f"{field}__last_name"]

    rows = rows.values(*values).annotate(
        debit_total=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
        credit_total=Coalesce(Sum("credit"), Value(ZERO), output_field=DecimalField()),
    )

    cells = defaultdict(lambda: ZERO)
    accounts = {}
    dimension_labels = {}

    for row in rows:
        account_uid = str(row["account__uid"])
        account_kind = row["account__kind"]
        section = _section_of(
            account_kind,
            row["account__account_type__title"],
            row["account__detail_type__title"],
        )
        if section is None:
            continue

        debit = Decimal(row["debit_total"] or 0)
        credit = Decimal(row["credit_total"] or 0)
        amount = (
            credit - debit
            if account_kind == ChartOfAccountKindChoices.INCOMES
            else debit - credit
        )

        accounts.setdefault(
            account_uid,
            {
                "uid": account_uid,
                "title": (row["account__title"] or "").strip() or "(untitled)",
                "section": section,
            },
        )

        if field:
            raw_uid = row.get(f"{field}__uid")
            if raw_uid:
                key = str(raw_uid)
                if key not in dimension_labels:
                    dimension_labels[key] = _dimension_label(row, field, dimension)
            else:
                key = UNASSIGNED_KEY
                dimension_labels.setdefault(UNASSIGNED_KEY, UNASSIGNED_LABEL)
        else:
            key = TOTAL_KEY

        cells[(key, account_uid)] += amount

    return cells, accounts, dimension_labels


def _dimension_label(row, field, dimension):
    if dimension == "customer":
        display = (row.get(f"{field}__display_name") or "").strip()
        if display:
            return display
        first = (row.get(f"{field}__first_name") or "").strip()
        last = (row.get(f"{field}__last_name") or "").strip()
        joined = " ".join(part for part in (first, last) if part)
        if joined:
            return joined
    return (row.get(f"{field}__title") or "").strip() or "(unnamed)"


class Ladder:
    """The P&L row ladder, filled across an arbitrary set of columns.

    Rows are flat and tagged by `kind` (`group` / `item` / `subtotal` /
    `total`), the convention the payroll `total-cost` report already
    established and which both specs ask for. Nesting is carried by the dotted
    key, so `expenses.payroll_expenses.wages` renders as a member of a group
    inside a group without the payload needing a tree.
    """

    def __init__(self, column_keys):
        self.column_keys = list(column_keys)
        self.rows = []

    def _values(self, reader):
        """Absent means no activity -- the key is omitted, not set to 0.00.

        Both specs are explicit about this: a missing key renders blank, which
        is how an account that did not exist in the comparison period reads
        differently from one that netted to zero.
        """
        values = {}
        for column_key in self.column_keys:
            amount = reader(column_key)
            if amount is None:
                continue
            values[column_key] = amount_string(amount)
        return values

    def group(self, key, label, reader=None):
        row = {"key": key, "label": label, "kind": "group"}
        if reader is not None:
            row["values"] = self._values(reader)
        self.rows.append(row)

    def item(self, key, label, reader, account_uid=None):
        row = {"key": key, "label": label, "kind": "item",
               "values": self._values(reader)}
        if account_uid:
            row["account_uid"] = account_uid
        self.rows.append(row)

    def subtotal(self, key, label, reader):
        self.rows.append({"key": key, "label": label, "kind": "subtotal",
                          "values": self._values(reader)})

    def total(self, key, label, reader):
        self.rows.append({"key": key, "label": label, "kind": "total",
                          "values": self._values(reader)})


def _slug(title):
    return "".join(
        character if character.isalnum() else "_" for character in title.lower()
    ).strip("_") or "account"


def build_ladder(column_keys, cells, accounts, *, split_payroll=True):
    """The full Income -> ... -> Net Income ladder across `column_keys`.

    `cells` maps `(column key, account uid)` to a Decimal.
    """
    by_section = defaultdict(list)
    for account in accounts.values():
        by_section[account["section"]].append(account)
    for section_accounts in by_section.values():
        section_accounts.sort(key=lambda a: a["title"].lower())

    def account_reader(account_uid):
        def read(column_key):
            return cells.get((column_key, account_uid))
        return read

    def section_reader(*sections):
        """A section total is always present, even at zero -- it anchors the ladder."""
        def read(column_key):
            total = ZERO
            for section in sections:
                for account in by_section.get(section, []):
                    total += cells.get((column_key, account["uid"]), ZERO)
            return total
        return read

    def combine(readers, signs):
        def read(column_key):
            total = ZERO
            for reader, sign in zip(readers, signs):
                total += sign * (reader(column_key) or ZERO)
            return total
        return read

    ladder = Ladder(column_keys)

    def emit_section(section_key, label, prefix, subtotal_label):
        ladder.group(prefix, label)
        for account in by_section.get(section_key, []):
            ladder.item(
                f"{prefix}.{_slug(account['title'])}",
                account["title"],
                account_reader(account["uid"]),
                account_uid=account["uid"],
            )
        ladder.subtotal(f"{prefix}.subtotal", subtotal_label,
                        section_reader(section_key))

    emit_section(INCOME, "Income", INCOME, "Total for Income")
    emit_section(COGS, "Cost of Goods Sold", COGS,
                 "Total for Cost of Goods Sold")

    income_reader = section_reader(INCOME)
    cogs_reader = section_reader(COGS)
    gross_profit = combine([income_reader, cogs_reader], [1, -1])
    ladder.total("gross_profit", "Gross Profit", gross_profit)

    # --- Expenses, with payroll carved out --------------------------------
    # The carve-out MUST exclude payroll from the plain expense list as well,
    # or "Total for Expenses" counts those accounts twice -- exactly the risk
    # the frontend spec flagged. `balance_sheet.py` does the same dance for
    # Payroll *Liabilities*.
    ladder.group(EXPENSES, "Expenses")
    payroll_accounts = by_section.get(PAYROLL_EXPENSES, [])
    if split_payroll and payroll_accounts:
        payroll_prefix = f"{EXPENSES}.{PAYROLL_EXPENSES}"
        ladder.group(payroll_prefix, "Payroll Expenses",
                     section_reader(PAYROLL_EXPENSES))
        for account in payroll_accounts:
            ladder.item(
                f"{payroll_prefix}.{_slug(account['title'])}",
                account["title"],
                account_reader(account["uid"]),
                account_uid=account["uid"],
            )
        ladder.subtotal(f"{payroll_prefix}.subtotal",
                        "Total for Payroll Expenses",
                        section_reader(PAYROLL_EXPENSES))
        expense_sections = (EXPENSES, PAYROLL_EXPENSES)
    else:
        # Not split: payroll accounts list inline with the rest.
        for account in payroll_accounts:
            ladder.item(
                f"{EXPENSES}.{_slug(account['title'])}",
                account["title"],
                account_reader(account["uid"]),
                account_uid=account["uid"],
            )
        expense_sections = (EXPENSES, PAYROLL_EXPENSES)

    for account in by_section.get(EXPENSES, []):
        ladder.item(
            f"{EXPENSES}.{_slug(account['title'])}",
            account["title"],
            account_reader(account["uid"]),
            account_uid=account["uid"],
        )
    expenses_reader = section_reader(*expense_sections)
    ladder.subtotal(f"{EXPENSES}.subtotal", "Total for Expenses",
                    expenses_reader)

    net_operating = combine([gross_profit, expenses_reader], [1, -1])
    ladder.total("net_operating_income", "Net Operating Income", net_operating)

    emit_section(OTHER_INCOME, "Other Income", OTHER_INCOME,
                 "Total for Other Income")
    emit_section(OTHER_EXPENSES, "Other Expenses", OTHER_EXPENSES,
                 "Total for Other Expenses")

    net_other = combine(
        [section_reader(OTHER_INCOME), section_reader(OTHER_EXPENSES)], [1, -1]
    )
    ladder.total("net_other_income", "Net Other Income", net_other)
    ladder.total("net_income", "Net Income",
                 combine([net_operating, net_other], [1, 1]))

    return ladder.rows


def pivot_columns(dimension_labels, cells):
    """Named dimension columns, "Not specified" last before Total.

    Only dimensions with activity get a column -- the same "don't invent empty
    columns" rule the payroll reports follow. "Not specified" collects
    everything unattributed so the columns always sum to the real total, which
    is the answer the by-store spec recommends for both reports.
    """
    active = {key for key, _ in cells}
    named = sorted(
        (key for key in dimension_labels if key != UNASSIGNED_KEY and key in active),
        key=lambda key: dimension_labels[key].lower(),
    )
    columns = [
        {"key": key, "label": dimension_labels[key], "is_total": False}
        for key in named
    ]
    if UNASSIGNED_KEY in active:
        columns.append(
            {"key": UNASSIGNED_KEY, "label": UNASSIGNED_LABEL, "is_total": False}
        )
    columns.append({"key": TOTAL_KEY, "label": "Total", "is_total": True})
    return columns


def add_total_column(cells, column_keys):
    """Fill the Total column by summing every other column, per account."""
    totals = defaultdict(lambda: ZERO)
    for (column_key, account_uid), amount in cells.items():
        if column_key == TOTAL_KEY:
            continue
        totals[account_uid] += amount
    for account_uid, amount in totals.items():
        cells[(TOTAL_KEY, account_uid)] = amount
    return cells
