"""A/R Aging Summary report builder.

Builds the Accounts Receivable Aging *Summary* described in
``docs/updated-prompts/AR_Aging_Summary_Documentation.md``: one rolled-up row per
customer, with that customer's open balance spread across the aging buckets
(Current / 1-30 / 31-60 / 61-90 / 91 and over) plus a Total column, a bottom
column-totals row, and a grand total.

It is the customer pivot of the A/R Aging Detail report: it reuses the same
source rows (``ar_aging_detail.open_ar_rows`` -- open invoices by stored
``Sale.due_total`` plus unapplied credit memos, aged by their own date and shown
negative) and the same party-neutral pivot engine as the A/P Aging Summary
(``ap_aging_summary.assemble_summary``, here grouping by customer). So the
Summary and Detail always reconcile, and each transaction ages on its own --
only the Total column nets them (doc section 5.4). The grand total agrees across
columns and down customer totals by construction (doc section 6.4).
"""

from datetime import date

from weapi.django_rest.helpers.reports.ap_aging_summary import assemble_summary
from weapi.django_rest.helpers.reports.ar_aging_detail import open_ar_rows


def ar_aging_summary(company, as_of=None, start_date=None, end_date=None):
    """Build the full A/R Aging Summary report for ``company``.

    ``as_of`` is the date aging is measured to (defaults to today -- the
    "All Dates" view). ``start_date``/``end_date`` (``date`` objects) optionally
    bound which transactions are in scope by their document date.
    """
    as_of = as_of or date.today()
    return assemble_summary(
        open_ar_rows(company, as_of, start_date, end_date),
        as_of,
        party="customer",
    )
