"""Derive account balances from journal lines instead of reading a stored one.

`ChartOfAccount.opening_balance` and `JournalEntryConnector.last_balance` are
snapshots written beside the ledger at posting time. They are the subject of
root cause R2: two places recording the same fact, which drift apart the moment
anything posts outside the one path that maintains them -- and `audit_ledger`
reports ~131k of exactly that.

The ledger lines are the record. A balance is a function of them, so it should
be computed when it is asked for, not stored and hoped over.

Two different questions get asked, and conflating them is its own bug:

* **movement** -- how much did this account move *during* a period. That is what
  a cost or activity report wants.
* **balance as of** -- where does this account stand at the end of a date, which
  is every line before that date, not only the ones inside the window.

`ChartOfAccount.get_last_balance` answered neither. It returned the newest
connector's stored `last_balance`, which is an account-wide running total
frozen at the moment of last activity -- so with a date filter it reported a
figure that belongs to no period at all, and without drift it was still wrong.

**Sign convention.** Every figure here is returned in the account's *natural*
direction, matching what `opening_balance` means and what a user expects to
read: assets and expenses are debit-positive, liabilities, equity and income are
credit-positive. A raw `debit - credit` would show every revenue account
negative.

**Date field.** Filtering is on `JournalEntryConnector.date`, the transaction
date, not `created_at`. The stored-balance code filtered on `created_at`, so a
backdated document counted into the period it was *entered* in rather than the
one it belongs to.
"""

from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from accounts.choices import ChartOfAccountKindChoices

from journalio.choices import JournalEntryConnectorKindChoices

ZERO = Decimal("0.000")

# Which side increases each kind. Kept here rather than derived from
# `get_debit_or_credit` at call time so the intent reads directly.
DEBIT_NATURAL_KINDS = frozenset(
    {ChartOfAccountKindChoices.ASSETS, ChartOfAccountKindChoices.EXPENSES}
)


def is_debit_natural(kind):
    """Whether a debit increases this kind of account."""
    return kind in DEBIT_NATURAL_KINDS


def to_natural(debit_total, credit_total, kind):
    """Signed balance in the account's own direction."""
    debit = Decimal(str(debit_total or 0))
    credit = Decimal(str(credit_total or 0))
    return debit - credit if is_debit_natural(kind) else credit - debit


def _summed(queryset):
    totals = queryset.aggregate(
        debit=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
        credit=Coalesce(Sum("credit"), Value(ZERO), output_field=DecimalField()),
    )
    return totals["debit"], totals["credit"]


def account_movement(account, dates=None):
    """How much `account` moved during `dates`, in its natural direction.

    `dates` is `[start, end]` inclusive, or None for the account's whole life.
    """
    queryset = account.journalentryconnector_set.all()
    if dates:
        start, end = dates
        if start:
            queryset = queryset.filter(date__gte=start)
        if end:
            queryset = queryset.filter(date__lte=end)
    debit, credit = _summed(queryset)
    return to_natural(debit, credit, account.kind)


def account_balance_as_of(account, as_of=None):
    """Where `account` stands at the end of `as_of` -- every line up to it.

    Distinct from `account_movement`: a closing balance includes history before
    the window, which is why a period-filtered movement cannot stand in for it.
    """
    queryset = account.journalentryconnector_set.all()
    if as_of:
        queryset = queryset.filter(date__lte=as_of)
    debit, credit = _summed(queryset)
    return to_natural(debit, credit, account.kind)


def running_balances(connectors, opening=None):
    """`{connector pk: running balance}` for an ordered run of lines.

    The caller supplies the connectors already ordered as the report displays
    them -- a running balance is only meaningful against a defined order, and
    several of these querysets had none at all, so the column could not even be
    monotone within one account.

    `opening` maps account id to the balance carried in before the first line,
    so a period-filtered report continues from where the account actually stood
    rather than restarting at zero.
    """
    opening = opening or {}
    running = {}
    result = {}
    for connector in connectors:
        account = connector.account
        if account is None:
            result[connector.pk] = ZERO
            continue
        key = account.pk
        if key not in running:
            running[key] = Decimal(str(opening.get(key, 0)))
        running[key] += to_natural(connector.debit, connector.credit, account.kind)
        result[connector.pk] = running[key]
    return result


def natural_amount_expression():
    """Case expression giving each line's amount in its account's direction."""
    from django.db.models import Case, F, When

    return Case(
        When(
            account__kind__in=list(DEBIT_NATURAL_KINDS),
            then=F("debit") - F("credit"),
        ),
        default=F("credit") - F("debit"),
        output_field=DecimalField(max_digits=19, decimal_places=3),
    )


# What a register calls its two amount columns, by account type. The generic
# pair is Increase/Decrease; money accounts get the names an accountant expects.
REGISTER_COLUMN_LABELS = {
    "Bank": ("Deposit", "Payment"),
    "Credit Cards": ("Charge", "Payment"),
}
GENERIC_COLUMN_LABELS = ("Increase", "Decrease")


def register_column_labels(account):
    r"""Head the two amount columns of `account`'s register.

    A row carries `deposit` and `payment` -- the movement in the account's own
    direction, and against it. What those columns are *called* depends on the
    account: a bank deposits and pays, a credit card is charged and paid down,
    and everything else simply increases and decreases.

    Server-side because the client had no way to know. It was matching the
    account type title against /credit\s*card/i -- a user-editable string, in a
    regex, to decide how to label money. Renaming an account type silently
    relabelled the register.

    Keyed on the account type title rather than on `kind`, because kind cannot
    tell a bank from any other asset, and the distinction being drawn here is
    exactly that one.
    """
    title = getattr(getattr(account, "account_type", None), "title", None)
    increase, decrease = REGISTER_COLUMN_LABELS.get(title, GENERIC_COLUMN_LABELS)
    return {"deposit": increase, "payment": decrease}


def single_account_amount_expression(account_kind):
    """A line's natural amount when the account is already known.

    `natural_amount_expression` decides the sign from `account__kind`, which
    makes every query using it join `accounts_chartofaccount`. A register is one
    account, so its direction is a constant and the join is avoidable -- which
    matters here because this expression is evaluated inside a correlated
    subquery, once per row.
    """
    from django.db.models import F

    if is_debit_natural(account_kind):
        return F("debit") - F("credit")
    return F("credit") - F("debit")


def ledger_balance_subquery(scope, account_kind, order_by=("date", "id")):
    """Each line's true account balance, immune to how the view filters.

    `annotate_running_balance` computes the same figure with a window function
    and is cheaper -- but SQL evaluates WHERE *before* window functions, and
    DRF's `filter_queryset` runs after `get_queryset`, so the moment a caller
    filters (a date range, a search, a payee) the cumulative sum restarts at the
    first surviving row. Every balance on the page is then wrong, silently and
    plausibly: filter a $50,000 account to August and its first row reads as if
    the account opened the month at zero.

    A register is filtered constantly, and a balance that changes when you
    filter is not a balance. So this computes what the column actually means --
    every line of the account up to and including this one, in `order_by` --
    as a correlated subquery that no outer filter or ordering can reach into.
    One indexed range scan per row: dearer than a window, and correct.

    `scope` is the queryset defining which lines count toward the balance. It
    must be the same population the view lists, or the rows and the balance
    disagree -- notably both must take the same view of unpublished entries.
    """
    from django.db.models import OuterRef, Q, Subquery

    date_field, tiebreak = order_by
    earlier = (
        scope.filter(account_id=OuterRef("account_id"))
        .filter(
            Q(**{f"{date_field}__lt": OuterRef(date_field)})
            | Q(
                **{
                    date_field: OuterRef(date_field),
                    f"{tiebreak}__lte": OuterRef(tiebreak),
                }
            )
        )
        .order_by()
        .values("account_id")
        .annotate(total=Sum(single_account_amount_expression(account_kind)))
        .values("total")
    )
    return Coalesce(
        Subquery(
            earlier,
            output_field=DecimalField(max_digits=19, decimal_places=3),
        ),
        Value(ZERO),
        output_field=DecimalField(max_digits=19, decimal_places=3),
    )


def annotate_running_balance(queryset, order_by=("date", "id")):
    """Add a per-account cumulative `running_balance`, computed by the database.

    Ordering is applied here rather than left to the caller because a running
    balance is undefined without one -- and several of these report querysets
    had no `order_by` at all, so the stored column they used to display could
    not even be monotone down the page.

    The window is evaluated before LIMIT, so the figure stays correct across
    pages instead of restarting on each one.

    `id` breaks ties so the frame is deterministic: with a date-only ordering
    the default RANGE frame includes every peer sharing a date, which would give
    all of them the same end-of-day total rather than a per-line progression.
    """
    from django.db.models import F, Window

    return queryset.annotate(
        running_balance=Window(
            expression=Sum(natural_amount_expression()),
            partition_by=[F("account_id")],
            order_by=[F(field).asc() for field in order_by],
        )
    ).order_by(*order_by)


class DerivedRunningBalanceMixin:
    """Serve `last_balance` from the derived running balance, not the column.

    The stored `JournalEntryConnector.last_balance` is a snapshot taken when the
    line was written, and it drifts. The response field keeps its name because
    it is a frontend contract, but the value now comes from
    `annotate_running_balance`, and `running_balance` is exposed alongside it
    under the honest name -- the same pairing the balance-sheet report already
    settled on.

    Falls back to computing per row if the queryset was not annotated, so a
    serializer used outside its view still cannot emit the stale value.
    """

    def get_last_balance(self, instance):
        return self.get_running_balance(instance)

    def get_running_balance(self, instance):
        annotated = getattr(instance, "running_balance", None)
        if annotated is not None:
            return f"{Decimal(str(annotated)):.3f}"
        account = getattr(instance, "account", None)
        if account is None:
            return f"{ZERO:.3f}"
        return f"{account_balance_as_of(account, getattr(instance, 'date', None)):.3f}"
