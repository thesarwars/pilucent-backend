"""Undoing a customer payment: the invoices, the legs, the balances.

`DELETE /we/sales/payment-received/{uid}` set the document's status to REMOVED
and did nothing else. `get_status_all()` excludes REMOVED, so the payment
vanished from its own list and looked deleted -- while `JournalEntry.status` was
never touched, so both its legs stayed PUBLISHED and therefore stayed in the
bank register, in its running balance, in every report, and in the candidate set
`/reconcile/complete` offers.

That last one is the sharpest edge. A deleted payment remains a document the
reconciliation workspace asks the user to tick. Tick it and they have reconciled
a transaction that does not exist; leave it and the difference never reaches
zero. Either way the account cannot be honestly reconciled again, from one
delete, with nothing on screen explaining why.

The invoices were the other half. `apply_sale_payment` reduces an invoice's
`due_total` and flips it to PAID, and had no inverse -- so a deleted payment
left every invoice it settled still showing as paid, owing nothing, with no
payment behind it.

Shaped after `reverse_pay_bill_item_postings`, which has done all of this for
Pay Bills since `debebef3`.
"""

import logging

from decimal import Decimal

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.id_generator import get_unique_id

from journalio.choices import (
    JournalEntryConnectorRequestKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector

from salesio.choices import SalePaymentReceiveItemModelKindChoices

logger = logging.getLogger(__name__)


def unapply_sale_payment_items(payment):
    """Put every invoice this payment settled back where it was.

    Returns the total restored. Only SALE lines move an invoice -- a
    CREDIT_NOTE line records that a credit was used and owns no `due_total`.
    """
    restored = Decimal("0.000")
    items = payment.salepaymentreceiveitem_set.select_related("sale")
    for item in items:
        if item.model_kind != SalePaymentReceiveItemModelKindChoices.SALE:
            continue
        if item.sale is None or not item.used_total:
            continue
        try:
            restored += item.sale.unapply_sale_payment(item.used_total)
        except ValueError:
            logger.warning(
                "void_sale_payment: could not unapply %s from sale %s",
                item.used_total, item.sale_id,
            )
    return restored


def void_sale_payment_postings(payment, *, created_by=None):
    """Reverse everything the payment did. Returns the reversing entry or None.

    The original entry is left alone and a second one is posted with the sides
    flipped, marked DELETED, so the pair nets to zero and a deleted payment can
    still be explained afterwards. Erasing it instead is what made the expense
    delete unmeasurable -- see `expense_posting.py`.
    """
    entries = list(JournalEntry.objects.filter(sale_payment_receive=payment))
    if not entries:
        logger.info("void_sale_payment: payment %s had nothing posted", payment.pk)
        return None

    # Already reversed. Without this, a second call reverses the ORIGINAL legs
    # again -- the reversal's own legs are excluded below, so they do not cancel
    # it -- and the balances overshoot by the full amount the other way.
    if JournalEntryConnector.objects.filter(
        journal__in=entries,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
    ).exists():
        logger.info("void_sale_payment: payment %s is already reversed", payment.pk)
        return None

    originals = list(
        JournalEntryConnector.objects.filter(journal__in=entries)
        .select_related("account")
        .exclude(request_kind=JournalEntryConnectorRequestKindChoices.DELETED)
    )

    connector_data = []
    for original in originals:
        account = original.account
        if account is None:
            continue
        amount = original.debit if original.debit else original.credit
        if not amount:
            continue

        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        connector_data.append(
            (account, opposite, amount, account.opening_balance, None, original.saleitem, None)
        )

    if not connector_data:
        logger.info(
            "void_sale_payment: payment %s had entries but no reversible lines",
            payment.pk,
        )
        return None

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
        sale_payment_receive=payment,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        customer=payment.customer,
        created_by=created_by,
    )

    logger.info(
        "void_sale_payment: payment %s reversed by entry %s with %s line(s)",
        payment.pk, reversal.pk, len(connector_data),
    )
    return reversal
