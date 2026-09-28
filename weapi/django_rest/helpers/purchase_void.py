"""Undoing a bill: the payments, the stock, the layers, the legs, the balances.

`DELETE /we/purchases/{uid}` set the document's status to REMOVED and did
nothing else. The bill's A/P leg stayed PUBLISHED, so a bill that no longer
existed went on saying money was owed; the goods it received stayed received;
the cost layer it created stayed spendable; and the supplier's own balance kept
the figure the posting put there.

**The last of the five, and the one with the most ways to say no.** A bill sits
at the head of two chains that later documents attach to:

* **Payments.** A bill is settled through `PurchasePaymentItem` (a supplier
  payment) and through `PayBillApplication` (Pay Bills). Neither writes a leg
  attributable to the bill, so there is nothing to flip -- unwinding one means
  rewriting a second posted document. Delete those first; both paths reverse
  properly now.
* **Stock.** A `PURCHASE` movement is a cost layer, and buying stock in order to
  sell it is the ordinary case. Once a sale has drawn on the layer, the units are
  gone and there is no honest reversal.

So this refuses far more often than it reverses, and that is correct: a bill that
has been paid or whose goods have been sold is not a mistake to erase, it is
history to correct with a new document.

**The supplier move is the mirror of the payment one, and the sign is the trap.**
Creating a bill passes CREDIT to `update_opening_balance` -- which means *add*,
not an accounting side -- so the bill ADDS to what the vendor is owed. Undoing it
subtracts. `void_purchase_payment_postings` does the opposite for the opposite
reason, and reading one as a template for the other is how a sign error gets in.

Driven off `StockMovement` rather than off `purchaseitem_set`, for the reason
`stock_adjustment_posting` and `credit_note_void` are: the movement ledger is
append-only and therefore still describes what posted.
"""

import logging

from decimal import Decimal

from rest_framework.serializers import ValidationError

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.id_generator import get_unique_id

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector

from purchaseio.choices import (
    PayBillItemStatusChoices,
    PurchasePaymentItemModelKindChoices,
    PurchasePaymentStatusChoices,
)

from stockio.choices import StockMovementTypeChoices
from stockio.django_rest.services.stock_movement import record_stock_movement
from stockio.models import StockMovement, StockMovementLayerConsumption

logger = logging.getLogger(__name__)


PAYABLE_TITLE = "Accounts Payable (A/P)"


class BillAlreadyPaid(ValidationError):
    """409-shaped refusal: a payment has already settled this bill."""


class BillStockConsumed(ValidationError):
    """409-shaped refusal: goods this bill received have since been used."""


# ---------------------------------------------------------------------------
# Refusal 1: the bill has been paid
# ---------------------------------------------------------------------------


def live_payments(purchase):
    """Payments still standing against this bill. `[(kind, uid, amount)]`.

    A deleted payment does not count. Its allocation rows survive the delete --
    only the payment's status changes -- and treating them as live would make a
    bill unfixable forever, with no way for the user out of the refusal.
    """
    settled = []

    for item in (
        purchase.purchasepaymentitem_set.filter(
            model_kind=PurchasePaymentItemModelKindChoices.PURCHASE
        )
        .exclude(purchase_payment__status=PurchasePaymentStatusChoices.REMOVED)
        .select_related("purchase_payment")
    ):
        amount = Decimal(str(item.used_total or 0))
        if amount and item.purchase_payment_id:
            settled.append(
                ("supplier payment", str(item.purchase_payment.uid), amount)
            )

    for application in (
        purchase.pay_bill_applications.exclude(
            pay_bill_item__status=PayBillItemStatusChoices.REMOVED
        ).select_related("pay_bill_item")
    ):
        amount = Decimal(str(application.amount or 0))
        if amount and application.pay_bill_item_id:
            settled.append(("pay bill", str(application.pay_bill_item.uid), amount))

    return settled


def assert_bill_not_paid(purchase):
    """Raise unless nothing has been paid against this bill."""
    settled = live_payments(purchase)
    if not settled:
        return

    raise BillAlreadyPaid(
        {
            "code": "BILL-ALREADY-PAID",
            "message": (
                "This bill cannot be deleted: it has already been paid by "
                f"{len(settled)} payment(s). Delete those first — doing so puts "
                "the bill back to owing — then delete the bill."
            ),
            "payments": [
                {"kind": kind, "uid": uid, "applied": float(amount)}
                for kind, uid, amount in settled
            ],
        }
    )


# ---------------------------------------------------------------------------
# Refusal 2: the goods have been used
# ---------------------------------------------------------------------------


def purchase_movements(purchase):
    """This bill's own inbound rows, oldest first. Never its REVERSALs.

    Filtered by `movement_type` as well as by the FK, because the reversal rows
    written below carry `purchase_item` too -- which is what makes a voided bill
    recognisable as voided, and what would make an FK-only query reverse its own
    reversals.
    """
    return list(
        StockMovement.objects.filter(
            purchase_item__purchase=purchase,
            movement_type=StockMovementTypeChoices.PURCHASE,
        )
        .select_related("product", "purchase_item")
        .order_by("id")
    )


def _own_reversals(purchase):
    return StockMovement.objects.filter(
        purchase_item__purchase=purchase,
        movement_type=StockMovementTypeChoices.REVERSAL,
    )


def _layer_unit_cost(movement):
    """What `ledger_layers` would price this layer at, derived the same way."""
    unit_cost = Decimal(str(movement.rate or 0))
    if not unit_cost and movement.signed_quantity:
        unit_cost = abs(Decimal(str(movement.inventory_cost or 0))) / Decimal(
            movement.signed_quantity
        )
    return unit_cost


def consumed_layers(purchase, movements=None):
    """Layers this bill created that anything has drawn on. `[(layer, taken)]`.

    Unlike a stock adjustment, there is no "internal" consumption to exclude: a
    bill only ever brings goods IN, so nothing it writes can consume its own
    layers. Any consumption at all is somebody else's.
    """
    movements = purchase_movements(purchase) if movements is None else movements
    if not movements:
        return []

    ours = {movement.pk for movement in movements}
    ours |= set(_own_reversals(purchase).values_list("pk", flat=True))

    taken = {}
    for row in StockMovementLayerConsumption.objects.filter(
        source_movement__in=movements
    ).exclude(movement_id__in=ours):
        quantity = Decimal(str(row.quantity_consumed or 0))
        if not quantity:
            continue
        taken[row.source_movement_id] = taken.get(
            row.source_movement_id, Decimal("0")
        ) + quantity

    return [
        (movement, taken[movement.pk])
        for movement in movements
        if taken.get(movement.pk, Decimal("0")) > 0
    ]


def assert_stock_not_consumed(purchase, movements=None):
    """Raise unless every layer this bill created is still whole."""
    consumed = consumed_layers(purchase, movements=movements)
    if not consumed:
        return

    named = ", ".join(
        f"{movement.product.title} ({quantity:g} of {movement.signed_quantity})"
        for movement, quantity in consumed
    )
    raise BillStockConsumed(
        {
            "code": "STOCK-ALREADY-CONSUMED",
            "message": (
                "This bill cannot be deleted: goods it received have since been "
                f"sold or used ({named}). Record the return with a credit note "
                "instead, so both movements stay on the record."
            ),
            "products": [
                {
                    "uid": str(movement.product.uid),
                    "title": movement.product.title,
                    "received": movement.signed_quantity,
                    "consumed": float(quantity),
                }
                for movement, quantity in consumed
            ],
        }
    )


# ---------------------------------------------------------------------------
# The inventory undo
# ---------------------------------------------------------------------------


def _on_hand_now(movement):
    """`movement.product`, re-read.

    Each movement carries its own `Product` instance from `select_related`, so
    two lines of one bill against the same product hold two copies of
    `quantity` and the second write discards the first.
    """
    product = movement.product
    product.refresh_from_db(fields=["quantity"])
    return product


def _withdraw_units(movement):
    """Units off hand, and the layer this line created spent down to nothing.

    Consumes the layer explicitly rather than through `consumption_slices`,
    which walks oldest-first and would take the units off whatever layer happens
    to be older -- silently repricing the stock still on hand.
    """
    quantity = int(movement.signed_quantity or 0)
    if quantity <= 0:
        return 0

    product = _on_hand_now(movement)
    on_hand = int(product.quantity or 0)
    if on_hand < quantity:
        # Reachable without any layer consumption: a flow that decremented
        # on-hand without recording against this layer, or a bill whose ledger
        # write failed (it is best-effort) after the serializer had already
        # moved the quantity. Refuse rather than let `Product.quantity`'s
        # PositiveIntegerField check surface as a 500.
        raise BillStockConsumed(
            {
                "code": "STOCK-ALREADY-CONSUMED",
                "message": (
                    "This bill cannot be deleted: it received "
                    f"{quantity} of {product.title}, but only {on_hand} remain "
                    "on hand. Record the return with a credit note instead."
                ),
                "products": [
                    {
                        "uid": str(product.uid),
                        "title": product.title,
                        "received": quantity,
                        "on_hand": on_hand,
                    }
                ],
            }
        )

    product.quantity = on_hand - quantity
    product.save(update_fields=["quantity"])

    record_stock_movement(
        company=movement.company,
        product=product,
        date=movement.date,
        movement_type=StockMovementTypeChoices.REVERSAL,
        signed_quantity=-quantity,
        rate=movement.rate,
        inventory_cost=-Decimal(movement.inventory_cost or 0),
        warehouse=movement.warehouse,
        created_by=movement.created_by,
        purchase_item=movement.purchase_item,
        layer_slices=[(movement, Decimal(quantity), _layer_unit_cost(movement))],
        note=f"Reversal of movement {movement.id}",
    )
    return quantity


def restore_purchase_inventory(purchase):
    """Take the goods back off. Returns `{"withdrawn": …, "lines": …}`.

    Idempotent: a bill that already carries REVERSAL rows has been through here.

    `PurchaseItem.quantity` and `opening_quantity` are zeroed alongside. The
    create path sets both to the line quantity, and they are the legacy FIFO
    source that `fifo_product_deduction` still walks -- so a bill left with them
    intact goes on offering stock the ledger says is gone.
    """
    result = {"withdrawn": 0, "lines": 0}
    movements = purchase_movements(purchase)
    if not movements:
        logger.info("void_purchase: bill %s moved no stock", purchase.pk)
        return result

    if _own_reversals(purchase).exists():
        logger.info("void_purchase: bill %s inventory already restored", purchase.pk)
        return result

    assert_stock_not_consumed(purchase, movements=movements)

    for movement in movements:
        result["withdrawn"] += _withdraw_units(movement)
        item = movement.purchase_item
        if item is not None:
            item.quantity = 0
            item.opening_quantity = 0
            item.save(update_fields=["quantity", "opening_quantity"])
            result["lines"] += 1

    logger.info(
        "void_purchase: bill %s withdrew %s unit(s) across %s line(s)",
        purchase.pk, result["withdrawn"], result["lines"],
    )
    return result


# ---------------------------------------------------------------------------
# The journal undo
# ---------------------------------------------------------------------------


def void_purchase_postings(purchase, *, created_by=None):
    """Reverse the journal. Returns `(reversal, supplier_amount)`.

    `supplier_amount` comes from the A/P leg rather than from `purchase.total`.
    The supplier move at post time is gated on `is_bill` -- a cheque purchase
    moves no supplier balance and writes no A/P leg -- so keying off the leg
    makes the reversal conditional in exactly the same way the posting was.
    """
    entries = list(JournalEntry.objects.filter(purchase=purchase))
    if not entries:
        logger.info("void_purchase: bill %s had nothing posted", purchase.pk)
        return None, Decimal("0.000")

    if JournalEntryConnector.objects.filter(
        journal__in=entries,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
    ).exists():
        logger.info("void_purchase: bill %s is already reversed", purchase.pk)
        return None, Decimal("0.000")

    originals = list(
        JournalEntryConnector.objects.filter(journal__in=entries)
        .select_related("account")
        .exclude(request_kind=JournalEntryConnectorRequestKindChoices.DELETED)
    )

    supplier_amount = Decimal("0.000")
    connector_data = []
    for original in originals:
        account = original.account
        if account is None:
            continue
        amount = original.debit if original.debit else original.credit
        if not amount:
            continue

        if account.title == PAYABLE_TITLE:
            supplier_amount += Decimal(str(amount))

        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        # Seven elements: a bill's cost legs are line-attributed through
        # `purchase_item` at index 6. Dropping it would leave the reversal legs
        # unattributable to the line they undo.
        connector_data.append(
            (
                account,
                opposite,
                amount,
                account.opening_balance,
                None,
                None,
                original.purchase_item,
            )
        )

    if not connector_data:
        logger.info("void_purchase: bill %s had entries but no legs", purchase.pk)
        return None, Decimal("0.000")

    template = entries[0]
    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, template.company_id, "entry_number", "JE"
        ),
        date=purchase.date,
        amount=template.amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=template.kind,
        is_transaction=True,
        is_journal_entry=True,
        company=template.company,
        purchase=purchase,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        supplier=purchase.supplier,
        created_by=created_by,
    )

    logger.info(
        "void_purchase: bill %s reversed by entry %s with %s line(s)",
        purchase.pk, reversal.pk, len(connector_data),
    )
    return reversal, supplier_amount


def restore_supplier_balance(purchase, amount):
    """Take back off the vendor what raising the bill put on.

    **The opposite direction to the payment helper of the same name**, and the
    sign is the whole point. Raising a bill passes CREDIT to
    `update_opening_balance` (`serializers/purchases.py:679-683`), whose CREDIT
    means *add* -- not an accounting side -- so a bill ADDS to what the vendor is
    owed. Undoing it subtracts, which is DEBIT here. Paying a bill is the mirror:
    it subtracts, so `void_purchase_payment_postings` adds back.

    A Supplier has no account kind, so there is no side to resolve and this
    cannot go through `action_for_side`.
    """
    if not amount or purchase.supplier_id is None:
        return Decimal("0.000")
    update_opening_balance(
        purchase.supplier, JournalEntryConnectorKindChoices.DEBIT, amount, 0
    )
    return amount
