"""Undoing a supplier payment: the bills, the credit notes, the legs, the balances.

`DELETE /we/purchases/payments/{uid}` set the document's status to REMOVED and
did nothing else, so the payment vanished from its list while both its legs
stayed PUBLISHED -- and with them the payment itself: in the bank register, in
its running balance, in every report, and in the candidate set
`/reconcile/complete` offers. The funding leg is a bank leg, and
`candidate_connectors` filters on account, company, `journal__status` and date
but **never on document status**, so a deleted payment is still something the
reconciliation workspace asks the user to tick.

The twin of `sale_payment_posting.py`, with two differences that are not
cosmetic:

* **A payment line can point at a Purchase or at a CreditNote**, and the two
  unwind differently. A bill line restores `due_total`; a credit-note line
  restores the note's remaining `total` and its OPEN/CLOSE status.
* **A credit-note-only payment posts an entry with no legs at all.** The ledger
  half of the credit-note branch is commented out
  (`serializers/purchases.py:2835-2850`) while the entry is created
  unconditionally, so `connector_data` can be empty. Creating a "reversal" of
  nothing would add a second empty entry, so this bails first.
"""

import logging

from decimal import Decimal

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.id_generator import get_unique_id

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector

from creditnoteio.choices import CreditNoteStatusChoices

from purchaseio.choices import PurchasePaymentItemModelKindChoices

logger = logging.getLogger(__name__)


PAYABLE_TITLE = "Accounts Payable (A/P)"


def _payable_account(company):
    """The A/P control account, resolved the way the posting path resolves it.

    `get_chart_of_account` returns a `{title: account}` dict and resolves by
    `system_key` first, so a renamed A/P is still found -- which matters,
    because the account is user-renameable and this decides whether the
    supplier balance moves.
    """
    resolved = get_chart_of_account([PAYABLE_TITLE], company) or {}
    account = resolved.get(PAYABLE_TITLE)
    if account is None:
        logger.warning(
            "void_purchase_payment: no A/P account for company %s", company.pk
        )
    return account


def void_purchase_payment_postings(payment, *, created_by=None):
    """Reverse the ledger. Returns `(reversal, supplier_amount)`.

    `supplier_amount` is the amount that moved the **supplier's** stored balance,
    taken from the A/P leg rather than from `payment.total`. The two are equal
    today -- `payable_request_total_balance` is `validated_data["total"]` -- but
    the supplier move is *gated* on the A/P account existing
    (`serializers/purchases.py:2748-2758`), so keying off the leg is what makes
    the reversal conditional in the same way the posting was. Zero when no A/P
    leg was written, which is exactly when no supplier balance moved.
    """
    entries = list(JournalEntry.objects.filter(purchase_payment=payment))
    if not entries:
        logger.info("void_purchase_payment: payment %s had nothing posted", payment.pk)
        return None, Decimal("0.000")

    if JournalEntryConnector.objects.filter(
        journal__in=entries,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
    ).exists():
        logger.info("void_purchase_payment: payment %s is already reversed", payment.pk)
        return None, Decimal("0.000")

    originals = list(
        JournalEntryConnector.objects.filter(journal__in=entries)
        .select_related("account")
        .exclude(request_kind=JournalEntryConnectorRequestKindChoices.DELETED)
    )

    payable = _payable_account(payment.company)
    supplier_amount = Decimal("0.000")
    connector_data = []
    for original in originals:
        account = original.account
        if account is None:
            continue
        amount = original.debit if original.debit else original.credit
        if not amount:
            continue

        if payable is not None and account.pk == payable.pk:
            supplier_amount += Decimal(str(amount))

        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        connector_data.append(
            (account, opposite, amount, account.opening_balance, None)
        )

    if not connector_data:
        # A credit-note-only payment. Its entry exists but carries no legs, so
        # there is nothing to reverse and a "reversal" would be a second empty
        # entry under the same FK. The credit notes themselves are still
        # restored by `unapply_purchase_payment_items`.
        logger.info(
            "void_purchase_payment: payment %s had entries but no legs", payment.pk
        )
        return None, Decimal("0.000")

    template = entries[0]
    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, template.company_id, "entry_number", "JE"
        ),
        amount=template.amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=template.kind,
        is_transaction=True,
        is_journal_entry=True,
        company=template.company,
        purchase_payment=payment,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        supplier=payment.supplier,
        created_by=created_by,
    )

    logger.info(
        "void_purchase_payment: payment %s reversed by entry %s with %s line(s)",
        payment.pk, reversal.pk, len(connector_data),
    )
    return reversal, supplier_amount


def restore_supplier_balance(payment, amount):
    """Put back what paying the bill took off the supplier.

    Paying SUBTRACTS from what the vendor is owed
    (`serializers/purchases.py:2748-2753` passes DEBIT, which
    `update_opening_balance` reads as subtract), so undoing it adds back. CREDIT
    means "add" there -- not an accounting side; a Supplier has no kind for one
    to be resolved from, which is why this cannot go through `action_for_side`.
    """
    if not amount or payment.supplier_id is None:
        return Decimal("0.000")
    update_opening_balance(
        payment.supplier, JournalEntryConnectorKindChoices.CREDIT, amount, 0
    )
    return amount


def unapply_purchase_payment_items(payment):
    """Put every bill and credit note this payment settled back where it was.

    Returns `{"bills_restored": …, "credit_notes_restored": …}`.

    Aggregated per document before unapplying, because two lines of one payment
    can point at the same bill and `unapply_purchase_payment` caps each call at
    the remaining `deposit` -- so two half-sized calls restore less than one
    full-sized one.

    REMOVED lines are included deliberately. Deleting a payment *line* retires
    it without unapplying (`views/purchases.py:867-869`), so the bill is still
    carrying that line's effect and this is the only chance to give it back.
    """
    restored = {"bills_restored": Decimal("0.000"), "credit_notes_restored": Decimal("0.000")}

    by_bill = {}
    by_note = {}
    for item in payment.purchasepaymentitem_set.select_related("purchase", "credit_note"):
        if not item.used_total:
            continue
        if (
            item.model_kind == PurchasePaymentItemModelKindChoices.PURCHASE
            and item.purchase_id
        ):
            by_bill[item.purchase_id] = by_bill.get(
                item.purchase_id, Decimal("0.000")
            ) + Decimal(str(item.used_total))
        elif (
            item.model_kind == PurchasePaymentItemModelKindChoices.CREDIT_NOTE
            and item.credit_note_id
        ):
            by_note[item.credit_note_id] = by_note.get(
                item.credit_note_id, Decimal("0.000")
            ) + Decimal(str(item.used_total))

    from creditnoteio.models import CreditNote
    from purchaseio.models import Purchase

    for purchase_id, amount in by_bill.items():
        purchase = Purchase.objects.filter(pk=purchase_id).first()
        if purchase is None:
            continue
        try:
            restored["bills_restored"] += purchase.unapply_purchase_payment(amount)
        except ValueError:
            logger.warning(
                "void_purchase_payment: could not unapply %s from purchase %s",
                amount, purchase_id,
            )

    for note_id, amount in by_note.items():
        note = CreditNote.objects.filter(pk=note_id).first()
        if note is None:
            continue
        # `credit_note.total` is the note's REMAINING credit -- create subtracts
        # what was used (`serializers/purchases.py:2826`), so giving it back is
        # an addition. Status follows the same rule create used, except that a
        # REMOVED note stays removed: undoing a payment does not resurrect a
        # note somebody deleted.
        note.total = Decimal(str(note.total or 0)) + amount
        if note.status != CreditNoteStatusChoices.REMOVED:
            note.status = (
                CreditNoteStatusChoices.OPEN
                if note.total > 0
                else CreditNoteStatusChoices.CLOSE
            )
        note.save()
        restored["credit_notes_restored"] += amount

    return restored
