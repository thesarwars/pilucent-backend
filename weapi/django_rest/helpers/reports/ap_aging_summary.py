"""A/P Aging Summary report builder.

Builds the Accounts Payable Aging *Summary* described in
``docs/updated-prompts/AP_Aging_Summary_Documentation.md``: one rolled-up row per
vendor, with that vendor's open balance spread across the aging buckets
(Current / 1-30 / 31-60 / 61-90 / 91 and over) plus a Total column, a bottom
column-totals row, and a grand total.

It is the vendor pivot of the A/P Aging Detail report and shares the exact same
source rows (``ap_aging_detail.open_ap_rows`` -- open bills by stored
``due_total`` plus unapplied vendor credits, credits aged by their own date and
shown negative), so the two reports always reconcile. Each transaction ages on
its own, so a vendor can carry amounts in several buckets at once; only the
Total column nets them (doc section 5.4). The grand total is reachable two ways
-- across the column totals and down the vendor totals -- which agree by
construction here since one source feeds both axes (doc section 6.4).
"""

from datetime import date

from weapi.django_rest.helpers.reports.ap_aging_detail import (
    ZERO,
    _bucket_key,
    open_ap_rows,
)

# Buckets left-to-right as the summary grid presents them (doc section 4) --
# this is the reverse of the Detail's most-overdue-first band order.
SUMMARY_BUCKET_ORDER = ["current", "1_30", "31_60", "61_90", "90_plus"]
SUMMARY_BUCKET_LABELS = {
    "current": "Current",
    "1_30": "1 - 30",
    "31_60": "31 - 60",
    "61_90": "61 - 90",
    "90_plus": "91 and over",
}

_NO_PARTY_KEY = "__no_party__"


def assemble_summary(rows, as_of, party="vendor"):
    """Pure: pivot normalized ``rows`` into a party x bucket matrix.

    Each row's ``open_balance`` (already 2-dp) is added to its party's bucket
    cell, chosen by ``_bucket_key(_aging_date, as_of)``. Returns party rows (with
    per-party Total), the bottom column totals, and the grand total. Kept ORM-free
    so the four-pass math is unit-testable against the documentation's worked
    example.

    ``party`` selects the grouping key/label fields on each row and in the output:
    ``"vendor"`` (A/P, default) reads/writes ``vendor_uid``/``vendor_display_name``;
    ``"customer"`` (A/R) reads/writes ``customer_uid``/``customer_display_name``.
    """
    uid_key = f"{party}_uid"
    name_key = f"{party}_display_name"

    parties = {}
    for row in rows:
        key = row.get(uid_key) or _NO_PARTY_KEY
        entry = parties.get(key)
        if entry is None:
            entry = parties[key] = {
                uid_key: row.get(uid_key),
                name_key: row.get(name_key) or f"(No {party})",
                "buckets": {b: ZERO for b in SUMMARY_BUCKET_ORDER},
            }
        bucket = _bucket_key(row["_aging_date"], as_of)
        entry["buckets"][bucket] += row["open_balance"]

    column_totals = {b: ZERO for b in SUMMARY_BUCKET_ORDER}
    out_rows = []
    for entry in parties.values():
        buckets = entry["buckets"]
        # A party whose offsetting invoice/credit nets every bucket to zero has
        # nothing to show -- skip it (an all-blank row reads as a defect, and its
        # zero contributions don't change any total). A party that nets to a zero
        # *total* but still has non-zero bucket cells is kept: that detail (e.g.
        # an old credit against a newer invoice) is meaningful.
        if all(value == ZERO for value in buckets.values()):
            continue
        party_total = ZERO
        for bucket in SUMMARY_BUCKET_ORDER:
            value = buckets[bucket]
            column_totals[bucket] += value
            party_total += value
        out_rows.append(
            {
                uid_key: entry[uid_key],
                name_key: entry[name_key],
                "buckets": {b: float(buckets[b]) for b in SUMMARY_BUCKET_ORDER},
                "total": float(party_total),
            }
        )

    # Default sort: party name A->Z, then uid as a stable tiebreak so distinct
    # parties sharing a display name order deterministically.
    out_rows.sort(key=lambda r: ((r[name_key] or "").lower(), r[uid_key] or ""))

    grand_total = sum(column_totals.values(), ZERO)
    return {
        "as_of": as_of.isoformat(),
        "buckets": [
            {"key": b, "label": SUMMARY_BUCKET_LABELS[b]} for b in SUMMARY_BUCKET_ORDER
        ],
        "rows": out_rows,
        "column_totals": {b: float(column_totals[b]) for b in SUMMARY_BUCKET_ORDER},
        "total": float(grand_total),
    }


def ap_aging_summary(company, as_of=None, start_date=None, end_date=None):
    """Build the full A/P Aging Summary report for ``company``.

    ``as_of`` is the date aging is measured to (defaults to today -- the
    "All Dates" view). ``start_date``/``end_date`` (``date`` objects) optionally
    bound which transactions are in scope by their document date.
    """
    as_of = as_of or date.today()
    return assemble_summary(open_ap_rows(company, as_of, start_date, end_date), as_of)
