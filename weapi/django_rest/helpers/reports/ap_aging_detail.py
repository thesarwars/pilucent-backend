"""A/P Aging Detail report builder.

Builds the Accounts Payable Aging *Detail* report described in
``docs/updated-prompts/AP_Aging_Detail_Report_Documentation.md``: every OPEN
bill and every unapplied vendor credit, listed transaction-by-transaction and
filed into aging bands (Current / 1-30 / 31-60 / 61-90 / 91+) by days past due,
with per-band subtotals and a grand total.

Open balance for a bill comes from the canonical, stored ``Purchase.due_total``
-- the same field the v2 dashboard A/P aging card uses (see
``weapi/django_rest/helpers/dashboard/finance.py``), so this report ties to that
card. Note it is NOT guaranteed to equal the Balance Sheet's A/P line, which is
sourced independently from the GL (``Sum(ChartOfAccount.opening_balance)`` for
"Accounts Payable (A/P)"). In particular, bills settled through the separate
"Pay Bills" feature reduce the GL/Balance-Sheet A/P but do NOT decrement
``Purchase.due_total``, so such bills still appear here at full open balance --
only payments made through the PurchasePayment flow reduce a bill's open balance
on this report.

Vendor credits (``CreditNote``, ``kind=PURCHASE``) carry no due date and are
aged by their transaction date (doc section 5.4); they appear as negative
amounts because they reduce what is owed (doc section 6.3). Their remaining
balance is read from the stored ``CreditNote.total``, which the apply flow
decrements as the credit is used. ``get_purchase_remaining_balance`` used to
double-count applications on the purchase side; it now returns that same stored
total, so the two agree.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNote

from purchaseio.choices import (
    PurchasePaymentItemModelKindChoices,
    PurchasePaymentStatusChoices,
)

from weapi.django_rest.helpers.dashboard.finance import open_bills_qs

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# Band keys ordered most-overdue first -- matches the sample report, which lists
# "91 or more days past due" above "61 - 90 days past due". Empty bands are
# omitted from the output (doc section 3.2).
BAND_ORDER = ["90_plus", "61_90", "31_60", "1_30", "current"]
BAND_LABELS = {
    "90_plus": "91 or more days past due",
    "61_90": "61 - 90 days past due",
    "31_60": "31 - 60 days past due",
    "1_30": "1 - 30 days past due",
    "current": "Current",
}


def _money(value):
    """Quantize to 2 dp (currency) so listed rows always add up to the displayed
    subtotal. The underlying fields are stored at 3 dp."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _supplier_name(supplier):
    """display_name -> company_name -> first+last (mirrors finance._customer_name)."""
    if supplier is None:
        return None
    name = supplier.display_name or supplier.company_name
    if not name:
        name = f"{supplier.first_name or ''} {supplier.last_name or ''}".strip()
    return name or None


def credit_amounts(stored_total, applied_total):
    """Pure: resolve a vendor credit's ``(amount, open_balance)`` report values.

    The purchase apply-credit flow decrements the stored ``CreditNote.total`` by
    each applied amount AND records that amount as a
    ``PurchasePaymentItem.used_total``. So the stored total *is* the unapplied
    (remaining) balance, and the original transaction value is
    ``stored_total + applied_total``. Applications from a REMOVED payment are
    excluded upstream, because deleting one adds the credit back to the stored
    total and counting its items here too would inflate Amount by that much
    again. Both returned values are
    negative because a credit reduces A/P (doc section 6.3); Amount is the
    original full value per doc section 4.
    """
    remaining = _money(stored_total)
    original = _money(Decimal(stored_total) + Decimal(applied_total))
    return -original, -remaining


def _bucket_key(aging_date, as_of):
    """Walk the days-past-due ladder and stop at the first band it fits."""
    if aging_date is None:
        return "current"
    days = (as_of - aging_date).days
    if days <= 0:
        return "current"
    if days <= 30:
        return "1_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def assemble_report(rows, as_of, public_row=None):
    """Pure: bucket normalized ``rows`` into bands with subtotals + grand total.

    Each row is a dict of display fields plus the internal keys ``_aging_date``
    (``date`` or ``None``) and ``_has_due_date`` (``bool``, for sorting), with
    ``amount``/``open_balance`` already quantized to 2 dp. Kept free of any
    ORM/clock access so the band/subtotal/total math is unit-testable against the
    documentation's worked example.

    ``public_row`` renders each row for output; it defaults to the A/P row shape
    (``vendor_display_name``). The A/R Aging Detail report passes its own
    (customer-shaped) renderer so the two reports share this band/subtotal/total
    engine without diverging.
    """
    if public_row is None:
        public_row = _public_row
    banded = {key: [] for key in BAND_ORDER}
    for row in rows:
        banded[_bucket_key(row["_aging_date"], as_of)].append(row)

    out_bands = []
    total_amount = ZERO
    total_open = ZERO
    for key in BAND_ORDER:
        band_rows = banded[key]
        if not band_rows:
            continue
        # Within a band: dated bills oldest-due first, then no-due-date items
        # (vendor credits) by their own date -- the report's default sort.
        band_rows.sort(
            key=lambda r: (
                0 if r["_has_due_date"] else 1,
                r["_aging_date"] or date.max,
            )
        )
        subtotal_amount = sum((r["amount"] for r in band_rows), ZERO)
        subtotal_open = sum((r["open_balance"] for r in band_rows), ZERO)
        total_amount += subtotal_amount
        total_open += subtotal_open
        out_bands.append(
            {
                "key": key,
                "label": BAND_LABELS[key],
                "count": len(band_rows),
                "rows": [public_row(r) for r in band_rows],
                "subtotal": {
                    "amount": float(subtotal_amount),
                    "open_balance": float(subtotal_open),
                },
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "bands": out_bands,
        "total": {
            "amount": float(total_amount),
            "open_balance": float(total_open),
        },
    }


def _public_row(row):
    """Strip internal sort keys and coerce dates/money to JSON-friendly values."""
    return {
        "uid": row["uid"],
        "kind": row["kind"],
        "date": row["date"].isoformat() if row["date"] else None,
        "transaction_type": row["transaction_type"],
        "num": row["num"],
        "vendor_display_name": row["vendor_display_name"],
        "store_full_name": row["store_full_name"],
        "due_date": row["due_date"].isoformat() if row["due_date"] else None,
        "past_due": row["past_due"],
        "amount": float(row["amount"]),
        "open_balance": float(row["open_balance"]),
    }


def _bill_rows(company, as_of, start_date, end_date):
    qs = open_bills_qs(company).select_related("supplier", "warehouse")
    if start_date and end_date:
        # The report period bounds which bills are in scope by document date.
        qs = qs.filter(date__range=[start_date, end_date])

    rows = []
    for bill in qs:
        due = bill.due_date
        # Bills age by due date; fall back to the bill/document date if a bill
        # was entered without one (doc section 5.4).
        aging_date = due or bill.bill_date or bill.date
        past_due = None
        if due is not None:
            past_due = (as_of - due).days
            if past_due < 0:  # not yet due => Past due reads 0 (doc section 6.1)
                past_due = 0
        rows.append(
            {
                "uid": str(bill.uid),
                "kind": "BILL",
                "transaction_type": "Bill",
                "date": bill.bill_date or bill.date,
                "num": bill.purchase_id or "",
                "vendor_uid": str(bill.supplier.uid) if bill.supplier_id else None,
                "vendor_display_name": _supplier_name(bill.supplier),
                "store_full_name": bill.warehouse.title if bill.warehouse_id else "",
                "due_date": due,
                "past_due": past_due,
                "amount": _money(bill.total),
                "open_balance": _money(bill.due_total),
                "_aging_date": aging_date,
                "_has_due_date": due is not None,
            }
        )
    return rows


def _credit_rows(company, start_date, end_date):
    qs = (
        CreditNote.objects.filter(
            company=company, kind=CreditNoteKindChoices.PURCHASE
        )
        .exclude(
            status__in=[
                CreditNoteStatusChoices.DRAFT,
                CreditNoteStatusChoices.REMOVED,
            ]
        )
        .select_related("supplier", "warehouse")
        # One query for the applied-credit totals (avoids an N+1 over
        # get_purchase_remaining_balance) -- and we need the applications to
        # recover the original credit value for the Amount column.
        .annotate(
            applied_total=Coalesce(
                Sum(
                    "purchasepaymentitem__used_total",
                    filter=Q(
                        purchasepaymentitem__model_kind=(
                            PurchasePaymentItemModelKindChoices.CREDIT_NOTE
                        )
                    )
                    # A deleted payment no longer counts as an application.
                    # `Amount` here is reconstructed as stored_total +
                    # applied_total, and deleting a supplier payment now adds the
                    # credit back to the stored total -- so counting the removed
                    # payment's items as well reported the credit's original
                    # value inflated by exactly the amount that was given back.
                    & ~Q(
                        purchasepaymentitem__purchase_payment__status=(
                            PurchasePaymentStatusChoices.REMOVED
                        )
                    ),
                ),
                Value(ZERO),
                output_field=DecimalField(),
            )
        )
    )
    if start_date and end_date:
        qs = qs.filter(date__range=[start_date, end_date])

    rows = []
    for credit in qs:
        remaining = _money(credit.total)  # stored total = unapplied balance
        if remaining <= 0:  # fully applied credits drop off, like paid bills
            continue
        amount, open_balance = credit_amounts(credit.total, credit.applied_total)
        rows.append(
            {
                "uid": str(credit.uid),
                "kind": "VENDOR_CREDIT",
                "transaction_type": "Vendor Credit",
                "date": credit.date,
                "num": credit.credit_note_number or "",
                "vendor_uid": str(credit.supplier.uid) if credit.supplier_id else None,
                "vendor_display_name": _supplier_name(credit.supplier),
                "store_full_name": credit.warehouse.title if credit.warehouse_id else "",
                "due_date": None,
                "past_due": None,
                "amount": amount,
                "open_balance": open_balance,
                "_aging_date": credit.date,  # credits age by their own date
                "_has_due_date": False,
            }
        )
    return rows


def open_ap_rows(company, as_of, start_date=None, end_date=None):
    """Shared normalized A/P row set (open bills + unapplied vendor credits).

    Each row carries ``vendor_uid``/``vendor_display_name``, a 2-dp ``amount``
    and ``open_balance``, and the internal ``_aging_date``/``_has_due_date`` keys.
    Used by BOTH the A/P Aging Detail and Summary reports so they always
    reconcile off the same source rows.
    """
    return _bill_rows(company, as_of, start_date, end_date) + _credit_rows(
        company, start_date, end_date
    )


def ap_aging_detail(company, as_of=None, start_date=None, end_date=None):
    """Build the full A/P Aging Detail report for ``company``.

    ``as_of`` is the date aging is measured to (defaults to today -- the
    "All Dates" view). ``start_date``/``end_date`` (``date`` objects) optionally
    bound which transactions are in scope by their document date.
    """
    as_of = as_of or date.today()
    return assemble_report(open_ap_rows(company, as_of, start_date, end_date), as_of)
