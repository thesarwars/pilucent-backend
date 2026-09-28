"""The document a migrated opening balance needs, in whichever direction it runs.

`SUPPLIER_GAPS.md` D2. Both supplier create paths guarded the whole opening
balance block with `float(opening_balance) > 0`, so a NEGATIVE balance -- a
prepayment or an unused vendor credit carried in from the previous system, which
Standard §3 calls legitimate and §12.12 calls routine -- was written to
`Supplier.opening_balance` by `objects.create(**validated_data)` and then posted
nowhere. No document, no journal entry, no A/P movement. Silent subledger
corruption on the first import.

**Why a credit note and not a negative bill.** The obvious fix is to mirror the
positive path with the signs flipped, and it is wrong: `open_bills_qs` filters
`due_total__gt=0`, so a negative bill is invisible to the A/P ageing report and
to the dashboard card while its journal legs still move A/P. That is exactly the
divergence `audit_ledger --only subledger` was built to catch, reintroduced by
the fix for a different one.

A vendor owing US money is a vendor credit, and `ap_aging_detail` already knows
how to show one -- it reads `CreditNote` rows of kind PURCHASE and prints them as
negative amounts. So the negative case gets the document the reports already
understand.
"""

from decimal import Decimal

from common.django_rest.helpers.id_generator import get_unique_id

from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNote

from purchaseio.choices import PurchaseStatus
from purchaseio.models import Purchase

from salesio.choices import SalesStatusChoices
from salesio.models import Sale


def opening_balance_document(supplier, company, amount, *, date=None):
    """The document behind a vendor's migrated balance.

    Positive -- the vendor is owed -- is a bill. Negative is a vendor credit for
    the absolute value. Returns `(document, is_credit)`; the caller flips its
    journal legs on `is_credit`.
    """
    amount = Decimal(str(amount or 0))
    if amount == 0:
        return None, False

    if amount > 0:
        return (
            Purchase.objects.create(
                due_total=amount,
                total=amount,
                is_bill=True,
                status=PurchaseStatus.OPEN,
                supplier=supplier,
                company=company,
                **({"date": date} if date is not None else {}),
            ),
            False,
        )

    credit = abs(amount)
    return (
        CreditNote.objects.create(
            company=company,
            supplier=supplier,
            kind=CreditNoteKindChoices.PURCHASE,
            status=CreditNoteStatusChoices.OPEN,
            total=credit,
            credit_note_number=get_unique_id(
                CreditNote, company.id, "credit_note_number", "CN"
            ),
            **({"date": date} if date is not None else {}),
        ),
        True,
    )


def customer_opening_balance_document(customer, company, amount, *, created_by=None,
                                      date=None):
    """The same rule on the receivable side.

    The customer bulk importer carried the identical `> 0` guard, so a customer
    who arrived holding a credit had it written to their row and posted nowhere.
    The mirror rule says a defect fixed on one side and not the other stops being
    one defect and becomes two.

    Positive is an invoice. Negative is a credit memo for the absolute value, and
    `ar_aging_detail` already reads `CreditNote` rows of kind SALE and ages them
    by transaction date. Returns `(document, is_credit)`.
    """
    amount = Decimal(str(amount or 0))
    if amount == 0:
        return None, False

    if amount > 0:
        return (
            Sale.objects.create(
                invoice_id=get_unique_id(Sale, company.id, "invoice_id", "INV"),
                total=amount,
                due_total=amount,
                is_invoice=True,
                status=SalesStatusChoices.OPEN,
                customer=customer,
                created_by=created_by,
                company=company,
                **({"date": date} if date is not None else {}),
            ),
            False,
        )

    credit = abs(amount)
    return (
        CreditNote.objects.create(
            company=company,
            customer=customer,
            kind=CreditNoteKindChoices.SALE,
            status=CreditNoteStatusChoices.OPEN,
            total=credit,
            credit_note_number=get_unique_id(
                CreditNote, company.id, "credit_note_number", "CN"
            ),
            **({"date": date} if date is not None else {}),
        ),
        True,
    )
