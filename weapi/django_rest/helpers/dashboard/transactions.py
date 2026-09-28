"""Shared recent-transactions builder.

One row per posted ``JournalEntry`` (a transaction document), shaped for the
frontend as ``{title, meta, amount, direction, date}``. Used by both the
Recent Transactions card and the Approval Center card.
"""

from journalio.models import JournalEntry
from journalio.choices import JournalEntryKindChoices


# kind -> human title shown on the transaction row
KIND_TITLE = {
    JournalEntryKindChoices.SALE: "Invoice",
    JournalEntryKindChoices.SALE_RECEPT: "Sale Receipt",
    JournalEntryKindChoices.REFUND_RECEIPT: "Refund",
    JournalEntryKindChoices.PURCHASE: "Bill",
    JournalEntryKindChoices.EXPENSE: "Expense",
    JournalEntryKindChoices.PURCHASE_PAYMENT: "Bill Payment",
    JournalEntryKindChoices.PAY_BILL: "Bill Payment",
    JournalEntryKindChoices.CHEQUE: "Cheque",
    JournalEntryKindChoices.CREDIT_NOTE: "Credit Note",
    JournalEntryKindChoices.STOCK_ADJUSTMENT: "Stock Adjustment",
}

# kinds that bring money in (everything else is treated as money out)
INFLOW_KINDS = {
    JournalEntryKindChoices.SALE,
    JournalEntryKindChoices.SALE_RECEPT,
}


def _reference_and_party(entry):
    if entry.sale_id:
        customer = entry.sale.customer.title if entry.sale.customer_id else None
        return entry.sale.invoice_id or entry.entry_number, customer
    if entry.sale_payment_receive_id:
        spr = entry.sale_payment_receive
        customer = spr.customer.title if spr.customer_id else None
        return (spr.reference_number or entry.entry_number), customer
    if entry.purchase_id:
        supplier = entry.purchase.supplier.title if entry.purchase.supplier_id else None
        return entry.entry_number, supplier
    if entry.expense_id:
        supplier = entry.expense.supplier.title if entry.expense.supplier_id else None
        return entry.entry_number, supplier
    return entry.entry_number, None


def recent_transactions(company, limit=10):
    entries = (
        JournalEntry.objects.filter(company=company)
        .exclude(status__in=["DRAFT", "REMOVED"])
        .select_related(
            "sale",
            "sale__customer",
            "sale_payment_receive",
            "sale_payment_receive__customer",
            "purchase",
            "purchase__supplier",
            "expense",
            "expense__supplier",
        )
        .order_by("-date", "-created_at")[:limit]
    )

    rows = []
    for entry in entries:
        reference, party = _reference_and_party(entry)
        meta = " • ".join([p for p in (reference, party) if p])

        amount_value = float(entry.amount or 0)
        direction = "in" if entry.kind in INFLOW_KINDS else "out"
        sign = "+" if direction == "in" else "-"

        rows.append(
            {
                "title": KIND_TITLE.get(entry.kind, entry.get_kind_display()),
                "meta": meta or None,
                "amount": f"{sign}${amount_value:,.2f}",
                "direction": direction,
                "date": entry.date.strftime("%b %d") if entry.date else None,
            }
        )
    return rows
