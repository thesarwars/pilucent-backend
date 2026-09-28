"""Balance sheet as of a date, built from the journal.

A balance sheet is cumulative -- every posting from the beginning of time up to
the as-of date -- which is why `collect_as_of` has no start date. That also
makes it the right shape for a comparison: two as-of dates, two columns.

Like `profit_loss_engine`, this deliberately does not reuse the existing
balance-sheet aggregation. That one sums `ChartOfAccount.opening_balance`,
a lifetime running balance, so both columns of a comparison would return the
same number regardless of the dates asked for.

The category names are `categoryio.Category` titles from the chart-of-accounts
seed; the existing view hard-codes the same literals.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from accounts.choices import ChartOfAccountKindChoices
from journalio.models import JournalEntryConnector


ZERO = Decimal("0.00")

BANK = "Bank"
RECEIVABLE = "Accounts Receivable (A/R)"
OTHER_CURRENT_ASSETS = "Other Current Assets"
FIXED_ASSETS = "Fixed Assets"
OTHER_ASSETS = "Other Assets"
PAYABLE = "Accounts Payable (A/P)"
CREDIT_CARDS = "Credit Cards"
OTHER_CURRENT_LIABILITIES = "Other Current Liabilities"
LONG_TERM_LIABILITIES = "Long Term Liabilities"
EQUITY = "Equity"
PAYROLL_LIABILITIES_DETAIL = "Payroll Liabilities"

# (key, label, account_type title, detail_type title or None)
# Payroll liabilities are carved out of Other Current Liabilities, and that
# group is then filtered to exclude them -- the existing view does the same,
# and skipping the exclusion would count those accounts twice.
SECTIONS = [
    ("assets.current_assets.bank_accounts", "Bank Accounts", BANK, None),
    ("assets.current_assets.accounts_receivable", "Accounts Receivable (A/R)",
     RECEIVABLE, None),
    ("assets.current_assets.other_current_assets", "Other Current Assets",
     OTHER_CURRENT_ASSETS, None),
    ("assets.fixed_assets", "Fixed Assets", FIXED_ASSETS, None),
    ("assets.other_assets", "Other Assets", OTHER_ASSETS, None),
    ("liabilities.current_liabilities.accounts_payable",
     "Accounts Payable (A/P)", PAYABLE, None),
    ("liabilities.current_liabilities.credit_cards", "Credit Cards",
     CREDIT_CARDS, None),
    ("liabilities.current_liabilities.payroll_liabilities",
     "Payroll Liabilities", OTHER_CURRENT_LIABILITIES,
     PAYROLL_LIABILITIES_DETAIL),
    ("liabilities.current_liabilities.other_current_liabilities",
     "Other Current Liabilities", OTHER_CURRENT_LIABILITIES, "-exclude-"),
    ("liabilities.long_term_liabilities", "Long Term Liabilities",
     LONG_TERM_LIABILITIES, None),
    ("equity", "Equity", EQUITY, None),
]

_BALANCE_KINDS = [
    ChartOfAccountKindChoices.ASSETS,
    ChartOfAccountKindChoices.LIABILITIES,
    ChartOfAccountKindChoices.EQUITIES,
]


def collect_as_of(company, as_of):
    """Signed balance per account, cumulative through `as_of`.

    Returns `(balances, accounts)` -- balances maps an account uid to a
    Decimal, accounts maps it to metadata including which section it belongs
    to. Assets increase on the debit side; liabilities and equity on the
    credit side.
    """
    rows = JournalEntryConnector.objects.filter(
        journal__company=company, account__kind__in=_BALANCE_KINDS
    ).exclude(account__status="REMOVED")
    if as_of:
        # The leg's own date, not the day it was typed. See
        # `profit_loss_engine` for why -- a report keyed on `created_at` moves
        # whenever an old document is amended.
        rows = rows.filter(date__lte=as_of)

    rows = rows.values(
        "account__uid",
        "account__title",
        "account__kind",
        "account__account_type__title",
        "account__detail_type__title",
    ).annotate(
        debit_total=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
        credit_total=Coalesce(Sum("credit"), Value(ZERO), output_field=DecimalField()),
    )

    balances = {}
    accounts = {}
    for row in rows:
        section = _section_for(
            row["account__account_type__title"], row["account__detail_type__title"]
        )
        if section is None:
            continue
        uid = str(row["account__uid"])
        debit = Decimal(row["debit_total"] or 0)
        credit = Decimal(row["credit_total"] or 0)
        amount = (
            debit - credit
            if row["account__kind"] == ChartOfAccountKindChoices.ASSETS
            else credit - debit
        )
        balances[uid] = amount
        accounts[uid] = {
            "uid": uid,
            "title": (row["account__title"] or "").strip() or "(untitled)",
            "section": section,
        }
    return balances, accounts


def _section_for(account_type_title, detail_type_title):
    for key, _, type_title, detail in SECTIONS:
        if account_type_title != type_title:
            continue
        if detail is None:
            return key
        if detail == "-exclude-":
            if detail_type_title != PAYROLL_LIABILITIES_DETAIL:
                return key
            continue
        if detail_type_title == detail:
            return key
    return None


def _amount(value):
    return f"{Decimal(value or 0).quantize(Decimal('0.01')):.2f}"


def build_comparison_rows(column_keys, balances_by_column, accounts,
                          net_income_by_column=None,
                          retained_prior_by_column=None):
    """The nested balance-sheet ladder across period columns.

    Every account row carries `account_uid` -- the whole point of the endpoint,
    since only the backend can align "the same account" across two periods. A
    column with no entry for an account omits the key rather than sending
    `"0.00"`, so an account that did not exist in the earlier period reads
    blank rather than as a real zero.
    """
    net_income_by_column = net_income_by_column or {}
    # Defaults to empty, so a caller that has not been taught the split yet gets
    # a zero prior-years row and an unchanged Net Income -- exactly today's
    # numbers, rather than an exception or a silently wrong equity total.
    retained_prior_by_column = retained_prior_by_column or {}

    by_section = defaultdict(list)
    for account in accounts.values():
        by_section[account["section"]].append(account)
    for section_accounts in by_section.values():
        section_accounts.sort(key=lambda a: a["title"].lower())

    def values_for(reader):
        values = {}
        for column_key in column_keys:
            amount = reader(column_key)
            if amount is None:
                continue
            values[column_key] = _amount(amount)
        return values

    def account_reader(uid):
        return lambda column_key: balances_by_column.get(column_key, {}).get(uid)

    def section_reader(*section_keys):
        def read(column_key):
            total = ZERO
            column = balances_by_column.get(column_key, {})
            for section_key in section_keys:
                for account in by_section.get(section_key, []):
                    total += column.get(account["uid"], ZERO)
            return total
        return read

    def sum_readers(readers):
        def read(column_key):
            return sum((reader(column_key) or ZERO for reader in readers), ZERO)
        return read

    rows = []

    def group(key, label, depth, reader=None):
        row = {"key": key, "label": label, "depth": depth, "is_group": True}
        if reader is not None:
            row["values"] = values_for(reader)
        rows.append(row)

    def total(key, label, depth, reader):
        rows.append({"key": key, "label": label, "depth": depth,
                     "is_total": True, "values": values_for(reader)})

    def emit(section_key, label, depth):
        group(section_key, label, depth)
        for account in by_section.get(section_key, []):
            rows.append(
                {
                    "key": f"{section_key}.{account['uid']}",
                    "label": account["title"],
                    "depth": depth + 1,
                    "account_uid": account["uid"],
                    "values": values_for(account_reader(account["uid"])),
                }
            )
        total(f"{section_key}.total", f"Total for {label}", depth + 1,
              section_reader(section_key))

    # --- Assets ------------------------------------------------------------
    group("assets", "Assets", 0)
    group("assets.current_assets", "Current Assets", 1)
    for key, label, *_ in SECTIONS[:3]:
        emit(key, label, 2)
    current_assets = section_reader(*[key for key, *_ in SECTIONS[:3]])
    total("assets.current_assets.total", "Total for Current Assets", 2,
          current_assets)
    emit("assets.fixed_assets", "Fixed Assets", 1)
    emit("assets.other_assets", "Other Assets", 1)
    assets = sum_readers([
        current_assets,
        section_reader("assets.fixed_assets"),
        section_reader("assets.other_assets"),
    ])
    total("assets.total", "Total for Assets", 1, assets)

    # --- Liabilities -------------------------------------------------------
    group("liabilities", "Liabilities", 0)
    group("liabilities.current_liabilities", "Current Liabilities", 1)
    current_liability_keys = [key for key, *_ in SECTIONS[5:9]]
    for key, label, *_ in SECTIONS[5:9]:
        emit(key, label, 2)
    current_liabilities = section_reader(*current_liability_keys)
    total("liabilities.current_liabilities.total",
          "Total for Current Liabilities", 2, current_liabilities)
    emit("liabilities.long_term_liabilities", "Long Term Liabilities", 1)
    liabilities = sum_readers([
        current_liabilities,
        section_reader("liabilities.long_term_liabilities"),
    ])
    total("liabilities.total", "Total for Liabilities", 1, liabilities)

    # --- Equity ------------------------------------------------------------
    # Net income is part of equity. Without it the sheet cannot balance, since
    # assets are financed by liabilities plus equity plus what was earned this
    # period. It gets its own row rather than being folded into the equity
    # accounts, which is how the printed reports show it.
    group("equity", "Equity", 0)
    for account in by_section.get("equity", []):
        rows.append(
            {
                "key": f"equity.{account['uid']}",
                "label": account["title"],
                "depth": 1,
                "account_uid": account["uid"],
                "values": values_for(account_reader(account["uid"])),
            }
        )
    equity_accounts = section_reader("equity")
    net_income = lambda column_key: net_income_by_column.get(column_key)
    # Defaults to ZERO rather than None, unlike every other reader here. An
    # account reader returns None for "this account did not exist in that
    # column", which `values_for` renders as a blank cell -- correct for an
    # account, wrong for this. Prior-year earnings always have a value, and a
    # caller that has not been taught the split yet should see "0.00" against
    # an unchanged Net Income, not an empty cell on a row that is always there.
    retained_prior = lambda column_key: retained_prior_by_column.get(column_key, ZERO)

    # Spec 5.1: `Assets = Liabilities + Contributed Capital + Retained Earnings
    # + (Income - Expenses) FOR THE CURRENT FISCAL YEAR`. One row carried the
    # whole lifetime under the label "Net Income", so a company in its third
    # year showed three years of earnings as this year's, and Retained Earnings
    # -- 0.000 on all 60 companies, because nothing has ever posted to it --
    # sat beside it reading as though the business had never made a penny.
    #
    # THIS IS A PARTITION OF A TOTAL THAT ALREADY EXISTS, NOT A NEW NUMBER.
    # The caller derives the current period by SUBTRACTING prior years from the
    # cumulative figure this row used to show, so:
    #
    #     retained_prior(D) + net_income(D) == the old single value, exactly
    #
    # holds by construction for every company, every as-of date and every
    # fiscal anchor -- algebraically, not by testing. `equity.total` and
    # `total_for_liabilities_and_equity` are therefore unchanged. If any edit
    # here makes that identity conditional on something, the edit is wrong.
    #
    # Two range queries on the two halves would NOT be a partition, which is
    # why it is done by subtraction. `net_income_from_journal` filters on
    # `created_at`, the row's INSERT timestamp, while a lower bound would
    # naturally be written against the accounting `date` -- and production has
    # rows where those disagree by months (co=122 connector 3927: dated
    # 2025-08-15, inserted 2026-01-29). Composed on different fields the two
    # halves can both exclude a line, dropping it from equity entirely, or both
    # include it and count it twice.
    #
    # The row is emitted whether or not it is zero. A company in its first year
    # showing "Retained Earnings (prior years) 0.00" is telling the truth; the
    # row appearing only sometimes would make the statement's shape depend on
    # the data, which breaks anything rendering a fixed layout.
    rows.append(
        {
            "key": "equity.retained_earnings_prior",
            "label": "Retained Earnings (prior years)",
            "depth": 1,
            "values": values_for(retained_prior),
        }
    )
    rows.append(
        {
            "key": "equity.net_income",
            "label": "Net Income",
            "depth": 1,
            "values": values_for(net_income),
        }
    )
    equity = sum_readers([equity_accounts, retained_prior, net_income])
    total("equity.total", "Total for Equity", 1, equity)

    total("total_for_liabilities_and_equity", "Total for Liabilities and Equity",
          0, sum_readers([liabilities, equity]))

    return rows
