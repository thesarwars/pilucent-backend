"""Current-period net income, for the Equity section of a balance sheet.

A balance sheet does not balance without it. Assets are financed by liabilities
plus equity, and equity includes what the business earned this period -- but the
balance-sheet views only sum the *equity accounts*, because their querysets are
scoped to `kind__in=[ASSETS, EQUITIES, LIABILITIES]` and never see an income or
expense account at all. On production that omission was ~90% of a $4.5m gap.

Two bases, deliberately:

* `net_income_from_balances` sums `ChartOfAccount.opening_balance`, matching how
  the existing balance-sheet and profit-loss views compute everything else. Its
  answer agrees with those reports even where the running balance has drifted
  from the journal.
* `net_income_from_journal` sums journal lines, matching the comparison engine.

They disagree wherever `opening_balance` has drifted -- on production, by
millions on one company. That is a data problem, not a reason to mix bases: each
report stays internally consistent by using the one its other figures use.
"""

from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from accounts.choices import ChartOfAccountKindChoices
from accounts.models import ChartOfAccount
from journalio.models import JournalEntryConnector
from weapi.django_rest.helpers.reports.account_activity import (
    with_journal_activity,
)


ZERO = Decimal("0.00")

NET_INCOME_KEY = "total_for_net_income"
NET_INCOME_LABEL = "Net Income"


def net_income_from_balances(company, start_date=None, end_date=None):
    """Income less expenses, on the stored-balance basis.

    Scoped from a fresh queryset rather than the caller's, so a drill-down
    filter on the balance sheet (`?account_type__title=...`) cannot silently
    reduce net income to zero.

    Cost of goods sold and other expenses need no special handling: both are
    `kind=EXPENSES` accounts, so summing the whole kind already covers them, and
    likewise other income is `kind=INCOMES`.
    """
    queryset = with_journal_activity(
        ChartOfAccount.objects.get_status_all().filter(company=company),
        start_date,
        end_date,
    )

    totals = queryset.aggregate(
        income=Coalesce(
            Sum(
                "opening_balance",
                filter=Q(kind=ChartOfAccountKindChoices.INCOMES),
            ),
            Value(ZERO),
            output_field=DecimalField(),
        ),
        expenses=Coalesce(
            Sum(
                "opening_balance",
                filter=Q(kind=ChartOfAccountKindChoices.EXPENSES),
            ),
            Value(ZERO),
            output_field=DecimalField(),
        ),
    )
    return Decimal(totals["income"] or 0) - Decimal(totals["expenses"] or 0)


def net_income_from_journal(company, as_of=None):
    """Income less expenses, cumulative through `as_of`, from journal lines.

    Income nets credit-debit and expenses net debit-credit, the convention in
    `common.django_rest.helpers.balance_helpers`.
    """
    rows = JournalEntryConnector.objects.filter(
        journal__company=company,
        account__kind__in=[
            ChartOfAccountKindChoices.INCOMES,
            ChartOfAccountKindChoices.EXPENSES,
        ],
    ).exclude(account__status="REMOVED")
    if as_of:
        # The leg's own date. Net income has to agree with the P&L above it,
        # and the P&L now scopes by the date the transaction belongs to.
        rows = rows.filter(date__lte=as_of)

    totals = rows.aggregate(
        income_credit=Coalesce(
            Sum("credit", filter=Q(account__kind=ChartOfAccountKindChoices.INCOMES)),
            Value(ZERO), output_field=DecimalField()),
        income_debit=Coalesce(
            Sum("debit", filter=Q(account__kind=ChartOfAccountKindChoices.INCOMES)),
            Value(ZERO), output_field=DecimalField()),
        expense_debit=Coalesce(
            Sum("debit", filter=Q(account__kind=ChartOfAccountKindChoices.EXPENSES)),
            Value(ZERO), output_field=DecimalField()),
        expense_credit=Coalesce(
            Sum("credit", filter=Q(account__kind=ChartOfAccountKindChoices.EXPENSES)),
            Value(ZERO), output_field=DecimalField()),
    )
    income = Decimal(totals["income_credit"] or 0) - Decimal(totals["income_debit"] or 0)
    expenses = Decimal(totals["expense_debit"] or 0) - Decimal(
        totals["expense_credit"] or 0
    )
    return income - expenses
