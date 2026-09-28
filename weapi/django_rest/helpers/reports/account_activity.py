"""Restrict a chart-of-account queryset to accounts with journal activity.

The reports all want "accounts that have at least one journal line, optionally
within a date range". Written the obvious way that is::

    queryset.filter(journalentryconnector__isnull=False).distinct()
            .filter(journalentryconnector__created_at__range=[start, end])

which is very slow for a subtle reason: two chained `.filter()` calls on the
same multi-valued relation produce two *separate* joins, so the row count is
accounts x lines x lines before `.distinct()` collapses it again. On production
that is a 104 x 1393 x 1393 intermediate -- roughly 200 million rows to answer a
question about 104 accounts -- and one balance-sheet request measured **8.37s**.

`Exists()` asks the same question as a correlated subquery: no fan-out, no
`.distinct()`, and the planner can stop at the first matching line. The same
request measured **0.04s**, returning identical figures and the identical 27
rows.

Date semantics are preserved exactly as the callers had them (`created_at`, a
datetime, compared against `YYYY-MM-DD`) so this is purely a performance change.
That comparison does silently exclude the final day -- worth fixing, but as its
own change with its own before/after, not folded in here.
"""

from django.db.models import Exists, OuterRef

from journalio.models import JournalEntryConnector


def has_journal_line(**line_filters):
    """`Exists` for a journal line on the outer account matching `line_filters`."""
    return Exists(
        JournalEntryConnector.objects.filter(account=OuterRef("pk"), **line_filters)
    )


def with_journal_activity(queryset, start_date=None, end_date=None):
    """Accounts in `queryset` having at least one journal line.

    When both dates are given the line must fall in that range. Callers no
    longer need `.distinct()` -- there is no join to duplicate rows.
    """
    lines = JournalEntryConnector.objects.filter(account=OuterRef("pk"))
    if start_date and end_date:
        lines = lines.filter(created_at__range=[start_date, end_date])
    return queryset.filter(Exists(lines))
