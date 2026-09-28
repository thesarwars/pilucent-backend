"""A/R Aging Detail report builder.

Builds the Accounts Receivable Aging *Detail* report described in
``docs/updated-prompts/AR_Aging_Detail_Report_Documentation.md``: every OPEN
invoice and every unapplied credit memo, listed transaction-by-transaction and
filed into aging bands (Current / 1-30 / 31-60 / 61-90 / 91+) by days past due,
with per-band subtotals and a grand total.

This is the customer-side mirror of the A/P Aging Detail report and shares its
band/subtotal/total engine (``ap_aging_detail.assemble_report``) and aging
ladder. Open balance for an invoice is the stored ``Sale.due_total`` -- the same
field the v2 dashboard A/R aging card uses (``finance.open_invoices_qs``), so the
report ties to that card. As on the A/P side, the GL-based Balance Sheet A/R line
is a separate source and may differ.

Credit memos (``CreditNote``, ``kind=SALE``) carry no due date and are aged by
their transaction date (doc section 5.4); they appear as negative amounts (doc
section 6.3). Unlike the purchase side, the sales credit-apply flow does NOT
mutate ``CreditNote.total``, so here ``total`` is the original Amount and the
open balance is ``get_sale_remaining_balance()`` = ``total - applied`` (computed
via a single annotation below to avoid an N+1).
"""

from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNote

from salesio.choices import (
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveStatusChoices,
)

from weapi.django_rest.helpers.dashboard.finance import open_invoices_qs
from weapi.django_rest.helpers.reports.ap_aging_detail import (
    ZERO,
    _money,
    assemble_report,
)


def _customer_name(customer):
    """display_name -> company_name -> first+last (mirrors finance._customer_name)."""
    if customer is None:
        return None
    name = customer.display_name or customer.company_name
    if not name:
        name = f"{customer.first_name or ''} {customer.last_name or ''}".strip()
    return name or None


def _public_row(row):
    """Strip internal sort keys and coerce dates/money to JSON-friendly values."""
    return {
        "uid": row["uid"],
        "kind": row["kind"],
        "date": row["date"].isoformat() if row["date"] else None,
        "transaction_type": row["transaction_type"],
        "num": row["num"],
        "customer_display_name": row["customer_display_name"],
        "store_full_name": row["store_full_name"],
        "due_date": row["due_date"].isoformat() if row["due_date"] else None,
        "past_due": row["past_due"],
        "amount": float(row["amount"]),
        "open_balance": float(row["open_balance"]),
    }


def _invoice_rows(company, as_of, start_date, end_date):
    qs = open_invoices_qs(company).select_related("customer", "warehouse")
    if start_date and end_date:
        # The report period bounds which invoices are in scope by document date.
        qs = qs.filter(date__range=[start_date, end_date])

    rows = []
    for invoice in qs:
        due = invoice.due_date
        # Invoices age by due date; fall back to the invoice/document date if one
        # was entered without a due date (doc section 5.4).
        aging_date = due or invoice.invoice_date or invoice.date
        past_due = None
        if due is not None:
            past_due = (as_of - due).days
            if past_due < 0:  # not yet due => Past due reads 0 (doc section 6.1)
                past_due = 0
        rows.append(
            {
                "uid": str(invoice.uid),
                "kind": "INVOICE",
                "transaction_type": "Invoice",
                "date": invoice.invoice_date or invoice.date,
                "num": invoice.invoice_id or "",
                "customer_uid": (
                    str(invoice.customer.uid) if invoice.customer_id else None
                ),
                "customer_display_name": _customer_name(invoice.customer),
                "store_full_name": (
                    invoice.warehouse.title if invoice.warehouse_id else ""
                ),
                "due_date": due,
                "past_due": past_due,
                "amount": _money(invoice.total),
                "open_balance": _money(invoice.due_total),
                "_aging_date": aging_date,
                "_has_due_date": due is not None,
            }
        )
    return rows


def _credit_rows(company, start_date, end_date):
    qs = (
        CreditNote.objects.filter(company=company, kind=CreditNoteKindChoices.SALE)
        .exclude(
            status__in=[
                CreditNoteStatusChoices.DRAFT,
                CreditNoteStatusChoices.REMOVED,
            ]
        )
        .select_related("customer", "warehouse")
        # Applied-credit total in one query (mirrors get_sale_remaining_balance,
        # which the sales side keeps correct because it does NOT mutate total).
        .annotate(
            applied_total=Coalesce(
                Sum(
                    "salepaymentreceiveitem__used_total",
                    filter=Q(
                        salepaymentreceiveitem__model_kind=(
                            SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE
                        )
                    )
                    # A deleted payment stops consuming the credit. Its item rows
                    # survive the delete -- only the payment's status changes --
                    # so without this the report goes on netting a credit against
                    # a receipt that is not on the books any more.
                    & ~Q(
                        salepaymentreceiveitem__sale_payment_receive__status=(
                            SalePaymentReceiveStatusChoices.REMOVED
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
        original = _money(credit.total)  # sales does not decrement total
        remaining = _money(Decimal(credit.total) - Decimal(credit.applied_total))
        if remaining <= 0:  # fully applied credits drop off, like paid invoices
            continue
        rows.append(
            {
                "uid": str(credit.uid),
                "kind": "CREDIT_MEMO",
                "transaction_type": "Credit Memo",
                "date": credit.date,
                "num": credit.credit_note_number or "",
                "customer_uid": (
                    str(credit.customer.uid) if credit.customer_id else None
                ),
                "customer_display_name": _customer_name(credit.customer),
                "store_full_name": (
                    credit.warehouse.title if credit.warehouse_id else ""
                ),
                "due_date": None,
                "past_due": None,
                "amount": -original,
                "open_balance": -remaining,
                "_aging_date": credit.date,  # credit memos age by their own date
                "_has_due_date": False,
            }
        )
    return rows


def open_ar_rows(company, as_of, start_date=None, end_date=None):
    """Normalized A/R row set (open invoices + unapplied credit memos)."""
    return _invoice_rows(company, as_of, start_date, end_date) + _credit_rows(
        company, start_date, end_date
    )


def ar_aging_detail(company, as_of=None, start_date=None, end_date=None):
    """Build the full A/R Aging Detail report for ``company``.

    ``as_of`` is the date aging is measured to (defaults to today -- the
    "All Dates" view). ``start_date``/``end_date`` (``date`` objects) optionally
    bound which transactions are in scope by their document date.
    """
    as_of = as_of or date.today()
    return assemble_report(
        open_ar_rows(company, as_of, start_date, end_date),
        as_of,
        public_row=_public_row,
    )
