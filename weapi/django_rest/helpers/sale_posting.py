"""Reverse what a sale posted, so it can be posted again from scratch.

`update()` currently amends a sale by *patching* what it already posted: it
finds the connector rows it wrote last time and assigns recomputed absolute
amounts onto them, while nudging `opening_balance` by a delta it works out on
the fly. Every finding in the sales audit that concerns amendment traces back to
that one decision:

* a price-only edit is not a quantity change, so the whole per-item block is
  skipped and income keeps the old figure while A/R moves (gap 4);
* a line consuming three FIFO layers wrote three connectors, and the patch
  rewrites `.first()` of them (gap 5);
* a line the user deleted is simply never visited, so its revenue, COGS and
  inventory relief stay live (gap 10);
* the tax breakdown is walked twice and posted again as if it were new (gap 3).

Patching cannot be made correct by adding more cases, because the set of things
that must change is not a function of what the payload happens to contain. The
standard remedy is to stop patching: **reverse the whole document, then post it
again from its persisted state.** The new posting is then produced by exactly
the same code that posts a brand-new sale, so an amended sale and a freshly
entered one with the same contents are indistinguishable in the ledger -- which
is the property all four findings are really asking for.

This module is the reversal half.

Two things are deliberately *not* symmetric with how the sale was posted:

**The journal is deleted; the stock ledger is not.** `JournalEntryConnector`
rows are working state for a document that is being rewritten in place, and the
repost re-emits them. `StockMovement` is an append-only ledger whose whole
contract is that rows are never mutated or deleted -- reports derive on-hand and
valuation by cumulating it in date order, so removing a row would silently
restate history. A reversal there is a compensating REVERSAL movement.

**Layer restoration reads the ledger, not the journal.**
`datamigrationio` has to *infer* how many units a connector consumed by dividing
its credit by the lot's purchase price, which cannot work for a zero-cost lot
and cannot see fallback units at all. `StockMovementLayerConsumption` records
the consumed quantity per lot directly, so restoring is exact -- including the
zero-price and layer-exhausted cases the division silently drops.
"""

import logging
from decimal import Decimal

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    get_migration_undo_balance_operation,
    update_opening_balance,
)

from journalio.choices import JournalEntryConnectorKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

logger = logging.getLogger(__name__)


def reverse_sale_postings(sale, *, restore_inventory=True):
    """Undo everything `sale` posted, leaving it ready to be posted again.

    Unwinds the stored balances its journal moved, restores the inventory it
    consumed, and drops the journal so the repost is not appended beside the old
    lines. Returns a summary dict for logging and tests.

    Caller must wrap this in `transaction.atomic()` together with the repost --
    a reversal that commits without its repost leaves the document with no
    journal at all.

    `restore_inventory=False` is for the case where the caller has already
    decided the goods are not coming back (a void that keeps the shipment).
    """
    summary = {
        "connectors_reversed": 0,
        "journal_entries_deleted": 0,
        "units_restored": 0,
        "layers_restored": 0,
        "customer_balance_reversed": Decimal("0.00"),
    }

    journal_entries = list(JournalEntry.objects.filter(sale=sale))
    connectors = list(
        JournalEntryConnector.objects.filter(journal__in=journal_entries)
        .select_related("account")
    )

    for connector in connectors:
        if _reverse_connector(connector):
            summary["connectors_reversed"] += 1

    summary["customer_balance_reversed"] = _reverse_customer_balance(sale)

    if restore_inventory:
        units, layers = restore_sale_inventory(sale)
        summary["units_restored"] = units
        summary["layers_restored"] = layers

    for journal_entry in journal_entries:
        # CASCADE takes the connectors with it. Deleting the connectors first
        # would trip the PROTECT on JournalEntryConnector.account.
        journal_entry.delete()
        summary["journal_entries_deleted"] += 1

    logger.info("reverse_sale_postings: sale=%s %s", getattr(sale, "id", None), summary)
    return summary


def _reverse_connector(connector):
    """Unwind one connector's effect on its account's stored balance."""
    account = connector.account
    if account is None:
        return False

    # Exactly one side is non-zero.
    amount = connector.debit if connector.debit else connector.credit
    if not amount:
        return False

    undo_op = get_migration_undo_balance_operation(account, connector.kind)
    update_opening_balance(account, undo_op, amount, account.opening_balance)
    return True


def _reverse_customer_balance(sale):
    """Unwind the receivable the sale put on the customer's own balance.

    The posting path moves `Customer.opening_balance` by `due_total` alongside
    the A/R control account, so a reversal that skipped it would leave the
    customer owing for an invoice that no longer exists.
    """
    customer = sale.customer
    if customer is None:
        return Decimal("0.00")

    due_total = Decimal(sale.due_total or 0)
    if due_total == 0:
        return Decimal("0.00")

    update_opening_balance(
        customer,
        JournalEntryConnectorKindChoices.DEBIT,
        due_total,
        customer.opening_balance,
    )
    return due_total


def restore_sale_inventory(sale):
    """Put back the stock this sale took out, lot by lot.

    Returns `(units_restored, layers_restored)`.

    Reads `StockMovementLayerConsumption` rather than reconstructing from the
    journal, so each lot gets back exactly the quantity it gave up. That matters
    for the two cases arithmetic on the journal cannot recover: a lot whose
    purchase price is zero (dividing cost by price is undefined) and units taken
    after the lots ran out, which have no lot at all.

    Only movements this sale has not already reversed are considered, so calling
    twice does not return the goods twice.
    """
    from stockio.choices import StockMovementTypeChoices
    from stockio.models import StockMovement

    units_restored = 0
    layers_restored = 0

    movements = (
        StockMovement.objects.filter(
            company=sale.company,
            sale_item__sale=sale,
            movement_type=StockMovementTypeChoices.SALE,
        )
        .select_related("product", "sale_item")
        .prefetch_related("layer_consumptions__purchase_item")
    )

    already_reversed = set(
        StockMovement.objects.filter(
            company=sale.company,
            sale_item__sale=sale,
            movement_type=StockMovementTypeChoices.REVERSAL,
        ).values_list("sale_item_id", flat=True)
    )

    for movement in movements:
        if movement.sale_item_id in already_reversed:
            logger.info(
                "restore_sale_inventory: movement %s already reversed, skipping",
                movement.id,
            )
            continue

        restored_here = 0
        for consumption in movement.layer_consumptions.all():
            quantity = int(Decimal(consumption.quantity_consumed or 0))
            if quantity <= 0:
                continue
            restored_here += quantity

            purchase_item = consumption.purchase_item
            if purchase_item is None:
                # A fallback slice -- taken when the lots were exhausted, so
                # there is no lot to credit. It still counts against on-hand.
                continue

            purchase_item.quantity = (purchase_item.quantity or 0) + quantity
            purchase_item.save(update_fields=["quantity"])
            layers_restored += 1

        if not restored_here:
            continue

        product = movement.product
        product.quantity = (product.quantity or 0) + restored_here
        product.save(update_fields=["quantity"])
        units_restored += restored_here

        _record_reversal_movement(movement, restored_here)

    return units_restored, layers_restored


def _record_reversal_movement(movement, quantity):
    """Append the compensating REVERSAL row for an undone SALE movement.

    Carries NEGATIVE layer slices mirroring what the original consumed. Cost
    layers are now read off this ledger, and a layer's remaining quantity is its
    inbound signed quantity less everything consumed against it -- so returning
    the goods without also undoing the attribution would hand the units back to
    on-hand while leaving the layer they came from looking spent. FIFO would
    then skip that layer and sell the same stock again at the next layer's cost,
    or at the zero fallback.

    A negative row rather than a deletion, because this ledger is append-only:
    the sum still nets to what is really left, and both the consumption and its
    undoing stay readable.

    Best-effort: the ledger is a reporting surface, and failing to write it must
    not roll back a correction to the books. It is logged loudly instead -- a
    silent gap here shows up later as a valuation report that disagrees with
    on-hand.
    """
    try:
        from stockio.choices import StockMovementTypeChoices
        from stockio.django_rest.services.stock_movement import record_stock_movement

        giving_back = [
            (
                consumption.source_movement or consumption.purchase_item,
                -Decimal(consumption.quantity_consumed or 0),
                Decimal(consumption.unit_cost or 0),
            )
            for consumption in movement.layer_consumptions.all()
            if consumption.quantity_consumed
        ]

        record_stock_movement(
            company=movement.company,
            product=movement.product,
            date=movement.date,
            movement_type=StockMovementTypeChoices.REVERSAL,
            signed_quantity=quantity,
            rate=movement.rate,
            inventory_cost=-Decimal(movement.inventory_cost or 0),
            warehouse=movement.warehouse,
            created_by=movement.created_by,
            sale_item=movement.sale_item,
            layer_slices=giving_back or None,
            note=f"Reversal of movement {movement.id}",
        )
    except Exception:
        logger.exception(
            "stock ledger: failed to record REVERSAL for movement %s", movement.id
        )


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------
#
# The other half of reverse-and-repost. `post_sale_document(sale)` emits the
# document's complete journal from its PERSISTED state -- the Sale row and its
# SaleItem rows -- and never looks at the incoming payload. That is the whole
# point: create() and update() can then post through identical code, so an
# amended document and a freshly entered one with the same contents produce the
# same ledger. Anything the poster cannot read off the model is, by definition,
# something an amendment would silently invent.
#
# Four traps that the payload-driven version hid, all of which this has to get
# right:
#
# 1. **Line order is an input.** FIFO consumes lots destructively, so for two
#    lines of the same product the iteration order decides which lots each line
#    eats and therefore each line's COGS. `SaleItem` declares no `Meta` and
#    inherits `ordering = ("-created_at",)`, so the default manager hands the
#    lines back REVERSED. Every read here is explicitly `order_by("id")`.
#
# 2. **The tax rate was never recorded.** `AgencyTaxSet.rate` and
#    `.sales_tax_account` are live configuration, so a repost priced tax at
#    whatever it is today. Posting now stamps `SaleItem.tax_snapshot` and a
#    repost prefers it.
#
# 3. **The SALE/REFUND guard did not mean what it read as.** The original
#    `is_invoice == True or is_sale_receipt == True and kind == SALE` binds
#    `and` tighter than `or`, so it is `is_invoice or (is_sale_receipt and kind
#    == SALE)` -- the `kind` test never applied to invoices at all, and an
#    invoice carrying `kind=REFUND` ran the SALE path: it deducted stock and
#    CREDITED revenue, exactly backwards, while the header was stamped
#    REFUND_RECEIPT. Direction is resolved once, explicitly, below.
#
# 4. **Inclusive tax was backed out once per LINE.** The document's `total_tax`
#    was subtracted from every line's revenue, so a three-line inclusive invoice
#    understated revenue by twice the tax and did not balance. It is now
#    apportioned across the lines pro rata.

from common.choices import DiscountKind, TaxKindChoices
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.fifo_product_quantity_helpers import (
    as_purchase_item,
    fifo_product_deduction,
)
from common.django_rest.helpers.quantity_helpers import update_quantity

from journalio.choices import (
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService

from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money

from salesio.choices import SaleItemStatusChoices, SaleReceptKindChoices
from salesio.models import SaleItem


def sale_lines(sale):
    """The document's live lines, in the order they were entered.

    `order_by("id")` is load-bearing, not tidiness -- see trap 1 above.
    """
    return (
        sale.saleitem_set.exclude(status=SaleItemStatusChoices.REMOVED)
        .select_related("product", "tax")
        .order_by("id")
    )


def is_posting_document(sale):
    """Whether this document belongs in the ledger at all.

    An estimate is a quote: it recognises nothing and must never move a stored
    balance.
    """
    return bool(sale.is_invoice or sale.is_sale_receipt)


def document_direction(sale):
    """SALE or REFUND, resolved once from persisted state.

    Deliberately NOT the original guard's shape -- see trap 3.
    """
    return (
        SaleReceptKindChoices.REFUND
        if sale.kind == SaleReceptKindChoices.REFUND
        else SaleReceptKindChoices.SALE
    )


def resolve_line_taxes(item):
    """`[(account, rate)]` this line posts tax to, preferring the snapshot.

    Reads `tax_snapshot` when present so an amendment reproduces the rate the
    document was filed with. Falls back to live configuration for lines posted
    before the column existed, and stamps them on the way through so each
    document self-heals the first time it is reposted.

    The gate is `is_tax AND tax` -- the FK is written unconditionally when a
    `tax_uid` is supplied, so testing the FK alone would start posting tax on
    documents that never had any.
    """
    from accounts.models import ChartOfAccount

    if not (item.is_tax and item.tax_id):
        return []

    snapshot = item.tax_snapshot
    if snapshot:
        resolved = []
        accounts = {
            a.pk: a
            for a in ChartOfAccount.objects.filter(
                pk__in=[row.get("account_id") for row in snapshot]
            )
        }
        for row in snapshot:
            account = accounts.get(row.get("account_id"))
            if account is None:
                logger.error(
                    "sale line %s: tax snapshot names account %s, which no longer "
                    "exists -- that tax leg cannot be reposted",
                    item.pk, row.get("account_id"),
                )
                continue
            resolved.append((account, Decimal(str(row.get("rate", 0)))))
        return resolved

    # No snapshot: read the live configuration and record it.
    live = []
    stamped = []
    for tax_set in item.tax.tax_groups.all():
        account = tax_set.sales_tax_account
        if account is None:
            continue
        rate = Decimal(str(tax_set.rate or 0))
        live.append((account, rate))
        stamped.append(
            {"tax_set_id": tax_set.pk, "account_id": account.pk, "rate": str(rate)}
        )

    if stamped:
        item.tax_snapshot = stamped
        item.save(update_fields=["tax_snapshot"])

    return live


def inclusive_tax_allocation(sale, lines):
    """How much of the document's tax to back out of each line's revenue.

    Inclusive tax sits inside the sale price, so revenue is the price net of it.
    The document carries a single `total_tax`, and the original code subtracted
    the whole of it from EVERY line -- a three-line invoice understated revenue
    by twice the tax and the entry did not balance.

    Apportioned pro rata by line value, with the rounding remainder given to the
    last line so the parts sum to exactly `total_tax`.
    """
    if sale.tax_kind != TaxKindChoices.INCLUSIVE:
        return {line.pk: Decimal("0.00") for line in lines}

    total_tax = quantize_money(sale.total_tax or 0)
    gross = {
        line.pk: quantize_money(Decimal(line.sale_price or 0) * (line.quantity or 0))
        for line in lines
    }
    basis = sum(gross.values())

    if not total_tax or basis <= 0:
        return {line.pk: Decimal("0.00") for line in lines}

    allocation = {}
    running = Decimal("0.00")
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            allocation[line.pk] = total_tax - running
        else:
            share = quantize_money(total_tax * gross[line.pk] / basis)
            allocation[line.pk] = share
            running += share
    return allocation


def resolve_discount_amount_for(sale):
    """The discount as a money amount, from persisted state.

    `discount` is a percentage or a flat amount depending on `discount_kind`, so
    it cannot be posted raw: a `10` on a 1,000 invoice is either 10.00 or 100.00.
    """
    discount = quantize_money(sale.discount or 0)
    if not discount:
        return Decimal("0.00")
    if sale.discount_kind == DiscountKind.PERCENTAGE:
        return quantize_money(quantize_money(sale.total or 0) * discount / Decimal("100"))
    return discount


def resolve_cogs_account(product, company):
    """Where this product's cost of sales is posted.

    `Product` carries `asset_account` and `income_account` as first-class fields
    but has no COGS field: the expense account lives on `ProductAdditionalCost`,
    a child row written only when the client sends a truthy `is_addtional_cost`.
    So whether an inventory item has a cost-of-sales account at all was the
    client's choice, and for an item created without one there was nowhere to
    post the cost.

    That mattered because the two legs were gated independently. Inventory Asset
    was relieved whether or not a COGS account existed, so a product with no cost
    row credited inventory with no offsetting debit -- an entry short by exactly
    the cost of goods sold, on an ordinary sale.

    Resolution order: the product's own cost row, then the company's COGS control
    account. The second is not a guess -- `COGS` is one of the ten system keys
    every company is required to have, so there is always a correct place for
    this, and skipping the leg was never the right answer.

    `.first()` on the cost rows is "latest row wins" under the model's
    `-created_at` ordering, which is its own defect: a product with two cost rows
    books COGS to whichever expense account was added last, regardless of the lot
    being consumed. Left as-is here; fixing it belongs with giving cost an
    effective date.
    """
    if product.cogs_account_id:
        return product.cogs_account
    additional_cost = product.productadditionalcost_set.first()
    if additional_cost and additional_cost.expense_account_id:
        return additional_cost.expense_account
    return get_chart_of_account(["Cost of Goods Sold (COGS)"], company).get(
        "Cost of Goods Sold (COGS)"
    )


def resolve_income_account(product, company):
    """Where this product's revenue is recognised.

    The revenue-side twin of `resolve_cogs_account`, and it exists because the
    two were asymmetric: cost fell back to the COGS control account when a
    product carried none, while revenue was `product.income_account` behind a
    bare `if income_account and line_income:` -- no fallback, and no log either,
    so a product without one debited the receivable and credited revenue
    nowhere. The entry came out short by the whole line, silently.

    `SALES_OF_PRODUCT_INCOME` is one of the system keys every company is
    required to have, so there is always a correct place for this. The same
    resolution already runs on the credit-note side (`fb21a01e`), which is the
    mirror of this leg -- leaving the sale side without it meant a sale and its
    own reversal disagreed about where revenue lived.
    """
    if product is not None and product.income_account_id:
        return product.income_account
    return get_chart_of_account(["Sales of Product Income"], company).get(
        "Sales of Product Income"
    )


def _post_sale_line(sale, line, tax_backout, connector_data):
    """Inventory relief, revenue and cost of sales for one outbound line."""
    product = line.product
    if product is None:
        return Decimal("0.00")

    quantity = int(line.quantity or 0)
    sale_price = Decimal(line.sale_price or 0)

    if not product.tracks_stock():
        # Revenue still posts below; there is simply no stock to relieve and no
        # cost of sales to recognise. Consuming FIFO layers for a service was
        # how a service line came to carry inventory COGS at all.
        deduction_details = []
    else:
        remaining, deduction_details, _groups = fifo_product_deduction(
            product, quantity
        )

    _record_movement(
        sale, line, product,
        movement_type="SALE",
        signed_quantity=-sum(int(q) for _pi, q, _p in deduction_details),
        rate=sale_price,
        layer_slices=deduction_details,
    )

    # --- Revenue -----------------------------------------------------------
    # Recognised from the document, once per line -- never from what FIFO
    # managed to deduct. A service item or an out-of-stock product consumes no
    # lots, and tying revenue to consumption produced a receivable with no
    # credit anywhere.
    income_account = resolve_income_account(product, sale.company)
    line_income = quantize_money(sale_price * quantity) - tax_backout

    if line_income and income_account is None:
        # Nothing left to fall back to. The receivable is debited either way,
        # so say so rather than shipping a short entry quietly -- the cost side
        # three blocks down has logged this case since `7cc3134c`.
        logger.error(
            "sale %s line %s: %s of revenue has no income account and the "
            "company has no Sales of Product Income control account. The "
            "entry will not balance.",
            sale.pk, line.pk, line_income,
        )

    if income_account and line_income:
        income_action = action_for_side(
            income_account.kind, JournalEntryConnectorKindChoices.CREDIT
        )
        update_opening_balance(
            income_account,
            balance_operation_for_action(income_action),
            line_income,
            0,
        )
        connector_data.append(
            (
                income_account,
                income_action,
                line_income,
                income_account.opening_balance,
                None,
                line,
                # Revenue belongs to the line, not to any one lot.
                None,
            )
        )

    # --- Cost of sales -----------------------------------------------------
    # These DO belong per lot: each consumed lot has its own cost, which is the
    # whole point of FIFO.
    cogs_account = resolve_cogs_account(product, sale.company)
    asset_account = product.asset_account
    total_cost = Decimal("0.00")

    if asset_account and not cogs_account:
        # Relieving inventory without recognising the cost leaves the entry
        # short by exactly that amount. Neither leg is posted, and it is said
        # loudly, rather than posting the half that happens to have an account.
        logger.error(
            "sale %s line %s: product %r has no cost-of-sales account and "
            "company %s has no COGS control account, so the inventory relief "
            "would have no counterpart. Neither leg posted.",
            sale.pk, line.pk, product.title, sale.company_id,
        )

    for layer_source, qty, price in deduction_details:
        # A layer may now be an opening balance or a return rather than a
        # purchase, and the connector's FK only accepts a purchase item.
        purchase_item = as_purchase_item(layer_source)
        if qty <= 0:
            continue
        cost = quantize_money(Decimal(price or 0) * qty)
        total_cost += cost

        # Posted as a pair or not at all -- see above.
        if not (cogs_account and asset_account):
            continue

        cogs_action = action_for_side(
            cogs_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            cogs_account, balance_operation_for_action(cogs_action), cost, 0
        )
        connector_data.append(
            (
                cogs_account, cogs_action, cost,
                cogs_account.opening_balance, None, line, purchase_item,
            )
        )

        asset_action = action_for_side(
            asset_account.kind, JournalEntryConnectorKindChoices.CREDIT
        )
        update_opening_balance(
            asset_account, balance_operation_for_action(asset_action), cost, 0
        )
        connector_data.append(
            (
                asset_account, asset_action, cost,
                asset_account.opening_balance, None, line, purchase_item,
            )
        )

    return total_cost


def _post_refund_line(sale, line, tax_backout, connector_data):
    """Restock, and reverse the revenue and cost of one returned line.

    `tax_backout` is the inclusive tax sitting inside this line's price, and it
    matters here for the same reason it does on the way out: under INCLUSIVE
    the price already contains the tax, so reversing the gross amount as revenue
    removes the tax from income while the tax legs are separately debiting the
    liability back. The refund then unwinds the tax twice.
    """
    from weapi.django_rest.helpers.purchase_item_helpers import (
        get_latest_published_purchase_item,
    )

    product = line.product
    if product is None:
        return Decimal("0.00")

    quantity = int(line.quantity or 0)
    sale_price = Decimal(line.sale_price or 0)
    # Net of the inclusive tax, mirroring `_post_sale_line`. Reversing gross
    # here is what removed the tax a second time.
    refund_amount = quantize_money(sale_price * quantity) - tax_backout

    purchase_item = get_latest_published_purchase_item(
        product=product, company=sale.company, date=sale.date
    )
    additional_cost = product.productadditionalcost_set.first()
    unit_price = Decimal("0.00")
    if purchase_item and purchase_item.purchase_price:
        unit_price = Decimal(purchase_item.purchase_price)
    elif additional_cost and additional_cost.amount:
        unit_price = Decimal(additional_cost.amount)
    refund_cost = quantize_money(unit_price * quantity)

    if purchase_item and quantity:
        purchase_item.quantity = (purchase_item.quantity or 0) + quantity
        purchase_item.opening_quantity = (purchase_item.opening_quantity or 0) + quantity
        purchase_item.save(update_fields=["quantity", "opening_quantity"])

    update_quantity(product, "addition", quantity, 0)

    # A return is the arithmetic inverse of the sale that took the stock out, so
    # it hands the units back to the layers that sale consumed, at the costs it
    # consumed them at -- negative slices.
    #
    # It used to pass POSITIVE slices, which are consumption rows: returning
    # stock took another unit out of the lot it came from. And `SALE_RETURN` was
    # a cost layer priced from `rate`, which is the SALE price. Measured on buy
    # 10 at 4 / sell 3 / return 1, the ledger ended up saying 8 units on hand
    # while its layers summed to 7 -- 6 at cost 4 plus a returned unit valued at
    # 10. Two defects that cancelled in the quantity and compounded in the cost.
    #
    # Units that match no consumption are real stock with no source in this
    # ledger -- a refund against a sale that predates it. They are recorded as
    # ADJUSTMENT_IN at cost rather than folded into the return, so they become a
    # layer (which the return no longer is) and so the two cases stay legible.
    if quantity:
        from stockio.django_rest.services.stock_movement import reversal_slices

        slices, unplaced = reversal_slices(product, quantity)

        _record_movement(
            sale, line, product,
            movement_type="SALE_RETURN",
            signed_quantity=quantity - unplaced,
            rate=sale_price,
            layer_slices=slices,
        )
        if unplaced:
            _record_movement(
                sale, line, product,
                movement_type="ADJUSTMENT_IN",
                signed_quantity=unplaced,
                rate=unit_price,
            )

    income_account = product.income_account
    if income_account and refund_amount:
        income_action = action_for_side(
            income_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            income_account,
            balance_operation_for_action(income_action),
            refund_amount,
            0,
        )
        connector_data.append(
            (
                income_account, income_action, refund_amount,
                income_account.opening_balance, None, line, None,
            )
        )

    asset_account = product.asset_account
    cogs_account = resolve_cogs_account(product, sale.company)

    if refund_cost <= 0:
        return refund_cost

    # Posted as a pair or not at all -- the same rule the sale path above
    # follows, and for the same reason. These two were gated independently, so
    # whichever leg happened to have an account posted alone and the entry was
    # short by the cost.
    #
    # It fired in production on 2026-08-07: journal 2766, a nightly recurring
    # refund, credited cost of sales 100 with no inventory debit and came out
    # -100. The product carries no asset_account, while resolve_cogs_account
    # falls back to the company's COGS control account -- so the cost half
    # resolved and the inventory half did not. The sale path gained this guard
    # with Product #5 (7cc3134c); the refund path was missed.
    if not (cogs_account and asset_account):
        logger.error(
            "sale %s line %s: refunding product %r would relieve cost without "
            "an offsetting inventory leg (cogs=%s, asset=%s). Neither leg "
            "posted.",
            sale.pk, line.pk, product.title,
            getattr(cogs_account, "pk", None), getattr(asset_account, "pk", None),
        )
        return refund_cost

    # The stored balance used to move the OPPOSITE way to the journal line
    # beside it: `debit` subtracts from the stored balance, while the
    # connector's "addition" resolves to an accounting DEBIT, i.e. inventory
    # going back up. Returned goods increase inventory, so the stored
    # balance has to increase with it.
    asset_action = action_for_side(
        asset_account.kind, JournalEntryConnectorKindChoices.DEBIT
    )
    update_opening_balance(
        asset_account, balance_operation_for_action(asset_action), refund_cost, 0
    )
    connector_data.append(
        (
            asset_account, asset_action, refund_cost,
            asset_account.opening_balance, None, line, purchase_item,
        )
    )

    cogs_action = action_for_side(
        cogs_account.kind, JournalEntryConnectorKindChoices.CREDIT
    )
    update_opening_balance(
        cogs_account, balance_operation_for_action(cogs_action), refund_cost, 0
    )
    connector_data.append(
        (
            cogs_account, cogs_action, refund_cost,
            cogs_account.opening_balance, None, line, purchase_item,
        )
    )

    return refund_cost


def _record_movement(sale, line, product, *, movement_type, signed_quantity, rate,
                     layer_slices=None):
    """Append to the stock ledger. Best-effort: never break a posting."""
    if not signed_quantity:
        return
    try:
        from stockio.choices import StockMovementTypeChoices
        from stockio.django_rest.services.stock_movement import record_stock_movement

        record_stock_movement(
            company=sale.company,
            product=product,
            date=sale.date,
            movement_type=getattr(StockMovementTypeChoices, movement_type),
            signed_quantity=signed_quantity,
            rate=rate,
            layer_slices=layer_slices,
            warehouse=getattr(sale, "warehouse", None),
            created_by=sale.created_by,
            sale_item=line,
        )
    except Exception:
        logger.exception(
            "stock ledger: failed to record %s for product %s on sale %s",
            movement_type, getattr(product, "id", None), getattr(sale, "id", None),
        )


def _post_tax_legs(sale, lines, direction, connector_data):
    """Sales-tax liability, per line and from the auto-tax breakdown.

    Posted at the rate the document was filed with -- see `resolve_line_taxes`.

    The balance move used to run unconditionally while its journal line was
    gated on the document's `total_tax != 0`, so a document carrying per-line
    tax but a zero document total moved the liability with nothing in the
    ledger to explain it. Both now happen together, always.
    """
    is_refund = direction == SaleReceptKindChoices.REFUND
    # Collecting tax CREDITS the liability; refunding it DEBITS. The side is
    # fixed by the direction, but the action that lands on it is not: it was
    # computed once here and reused for every account below, so one agency
    # account typed as something other than a liability posted the wrong way
    # while the rest of the entry was right.
    tax_side = (
        JournalEntryConnectorKindChoices.DEBIT
        if is_refund
        else JournalEntryConnectorKindChoices.CREDIT
    )
    posted = Decimal("0.00")

    is_inclusive = sale.tax_kind == TaxKindChoices.INCLUSIVE

    for line in lines:
        item_total = quantize_money(line.total or 0)
        for account, rate in resolve_line_taxes(line):
            if is_inclusive:
                # The line amount already CONTAINS the tax, so extract it
                # rather than add it on top. Adding on top charged 10% of a
                # tax-inclusive 100.00 as 10.00 when the tax inside it is 9.09,
                # and the same arithmetic the document's own total_tax was
                # computed with is the extraction, not the addition.
                #
                # Left the inclusive refund out by 0.910 after the backout fix
                # beside it closed the 10.000. No production document is
                # INCLUSIVE today -- every Purchase is NO_TAX, every Sale is
                # NO_TAX or EXCLUSIVE, no recurring template is inclusive -- so
                # this corrects a shape nobody has reached rather than restating
                # anybody's books.
                tax_amount = quantize_money(
                    item_total * rate / (Decimal("100") + rate)
                )
            else:
                tax_amount = quantize_money(item_total * rate / Decimal("100"))
            if not tax_amount:
                continue
            tax_action = action_for_side(account.kind, tax_side)
            update_opening_balance(
                account, balance_operation_for_action(tax_action), tax_amount, 0
            )
            posted += tax_amount
            connector_data.append(
                (
                    account, tax_action, tax_amount,
                    account.opening_balance, None, line, None,
                )
            )

    breakdown = (sale.auto_sales_tax or {}).get("breakdown") or {}
    if not breakdown:
        _post_unattributed_tax(sale, posted, tax_side, connector_data)
        return

    accounts = get_chart_of_account(list(breakdown), sale.company)
    for title, data in breakdown.items():
        account = accounts.get(title)
        amount = quantize_money(Decimal(str((data or {}).get("amount", 0))))
        if amount <= 0:
            continue
        if account is None:
            logger.error(
                "sale %s: auto sales tax names %r, which company %s has no "
                "account for -- that leg cannot be posted",
                sale.pk, title, sale.company_id,
            )
            continue
        tax_action = action_for_side(account.kind, tax_side)
        update_opening_balance(
            account, balance_operation_for_action(tax_action), amount, 0
        )
        posted += amount
        connector_data.append(
            (account, tax_action, amount, account.opening_balance, None, None, None)
        )

    _post_unattributed_tax(sale, posted, tax_side, connector_data)


def _post_unattributed_tax(sale, posted, tax_side, connector_data):
    """Post tax the document declares that nothing else accounted for.

    `total_tax` is a header figure the client sends, and the liability legs come
    from somewhere else entirely: the per-line tax rates, or the auto-tax
    breakdown. A document carrying `total_tax` with neither produced no tax leg
    at all, so the receivable was debited for the tax-inclusive amount and
    nothing was credited for the tax -- the entry short by exactly `total_tax`.
    On an INCLUSIVE document it is worse, because revenue is correctly reduced
    by the tax, making the missing credit the whole of it.

    Posts the SHORTFALL, not just the whole of an unattributed total. The
    original version returned as soon as any leg had posted, on the reasoning
    that topping up a header which disagrees with its own detail would hide the
    disagreement. The reasoning is right and the remedy was wrong: production
    company 165 collected 590.625 of tax into the bank, posted 37.50 of it to a
    liability, and shipped an entry short by 553.125 -- the log line was there
    and the ledger was still broken. An unbalanced entry is a worse way to keep
    a fault visible than a balanced entry plus a WARNING, so now it does both.

    The shortfall lands on Sales Tax Payable rather than the agency it belongs
    to, because which agency is exactly what the document failed to say. That is
    a mis-attribution -- a reporting problem with a loud log line -- instead of
    a ledger that does not balance.

    Never posts a negative leg. If the legs total MORE than the header the
    entry is over-credited, and the answer is not a negative-amount connector;
    that case is reported and left for a human.

    Reconciles against the HEADER, which assumes the receivable followed it --
    `due_total = total + total_tax - deposit` is what every document builder
    computes, so a customer billed for `total_tax` really was charged it and
    the liability has to match. A document whose receivable followed its LINES
    while its header said something else would be topped up wrongly here, but
    that document is already inconsistent before it reaches the ledger and the
    WARNING names it.
    """
    # `declared` is NOT quantized: it is the header the customer was billed,
    # and `posted` stays as accumulated because those legs really were written
    # at their own precision. The RESIDUAL is quantized, and that is the whole
    # trick -- see below.
    declared = Decimal(str(sale.total_tax or 0))
    if not declared:
        return

    # Quantized, because the legs this has to plug are.
    #
    # This was deliberately left unquantized, on the reasoning that the ledger
    # columns hold 3 places and rounding the HEADER to 590.63 would leave the
    # entry out by 0.005. The reasoning was right about the header and wrong
    # about the leg. Both counter-legs -- the receivable and the deposit --
    # already run through `quantize_money`, so on the production receipt the
    # bank was debited 8,090.63 while an unquantized residual credited
    # 8,090.625. Out by 0.005: a far smaller fault than the 553.125 it
    # replaced, and still a fault, which is exactly what the original comment
    # predicted and then walked into.
    #
    # Quantizing here lands on it exactly: 590.625 - 37.50 = 553.125 -> 553.13,
    # and 553.13 + 7,500 + 37.50 = 8,090.63. `quantize_money` is ROUND_HALF_UP,
    # the same rounding the counter-legs took, so the two agree by construction
    # rather than by luck.
    residual = quantize_money(declared - posted)
    if abs(residual) <= Decimal("0.01"):
        # The legs account for the header, give or take rounding.
        return

    if posted:
        logger.warning(
            "sale %s: declares total_tax %s but its tax legs total %s. The "
            "header disagrees with its own detail.",
            sale.pk, declared, posted,
        )

    if residual < 0:
        logger.error(
            "sale %s: tax legs total %s, MORE than the declared total_tax %s. "
            "Refusing to post a negative leg, so this entry will not balance "
            "-- the document's own tax detail needs correcting.",
            sale.pk, posted, declared,
        )
        return

    account = get_chart_of_account(["Sales Tax Payable"], sale.company).get(
        "Sales Tax Payable"
    )
    if account is None:
        logger.error(
            "sale %s: %s of declared tax is unaccounted for and company %s has "
            "no Sales Tax Payable account to post it to. The entry will not "
            "balance.",
            sale.pk, residual, sale.company_id,
        )
        return

    logger.info(
        "sale %s: %s of the declared total_tax %s reached no agency account -- "
        "posting the shortfall to Sales Tax Payable so the entry balances",
        sale.pk, residual, declared,
    )
    action = action_for_side(account.kind, tax_side)
    update_opening_balance(
        account, balance_operation_for_action(action), residual, 0
    )
    connector_data.append(
        (account, action, residual, account.opening_balance, None, None, None)
    )


def post_sale_document(sale, *, created_by=None,
                       request_kind=JournalEntryConnectorRequestKindChoices.CREATED):
    """Emit the complete journal for `sale` from its persisted state.

    Returns the `JournalEntry`, or None for a document that does not post.

    Reads nothing from the request payload, so `create()` and `update()` can
    both call it and an amended document lands in the ledger identically to a
    freshly entered one with the same contents.

    Caller is responsible for atomicity, and -- on an amendment -- for having
    reversed the previous posting first.
    """
    if not is_posting_document(sale):
        logger.info("post_sale_document: sale %s does not post (estimate)", sale.pk)
        return None

    company = sale.company
    direction = document_direction(sale)
    lines = list(sale_lines(sale))
    connector_data = []

    control = get_chart_of_account(
        ["Accounts Receivable (A/R)", "Sales Discounts", "Shipping Income"], company
    )
    receivable_account = control.get("Accounts Receivable (A/R)")

    # --- Lines -------------------------------------------------------------
    backouts = inclusive_tax_allocation(sale, lines)
    for line in lines:
        if direction == SaleReceptKindChoices.REFUND:
            # The backout goes to BOTH branches. `backouts` was computed here
            # and handed only to the sale side, so an inclusive-tax refund
            # reversed revenue GROSS while the tax legs debited the liability
            # back as well -- the tax removed twice, the entry out by it. A
            # refund is the sale run backwards; it needs the same arithmetic.
            _post_refund_line(sale, line,
                              backouts.get(line.pk, Decimal("0.00")),
                              connector_data)
        else:
            _post_sale_line(sale, line, backouts.get(line.pk, Decimal("0.00")),
                            connector_data)

    # --- Receivable --------------------------------------------------------
    due_total = quantize_money(sale.due_total or 0)
    if sale.customer_id and due_total:
        update_opening_balance(sale.customer, "credit", due_total, 0)

    if receivable_account is None:
        logger.error(
            "sale %s: company %s has no Accounts Receivable account -- the entry "
            "will not balance", sale.pk, company.pk,
        )
    elif due_total:
        # A/R's kind derives from an editable account type rather than being
        # fixed, which is what `repair_control_account_types` exists to correct
        # -- it repaired 62 control accounts on the production chart. On any
        # company where A/R had come out as an income kind, "addition" resolved
        # to a CREDIT and an invoice reduced what the customer owed.
        receivable_action = action_for_side(
            receivable_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            receivable_account,
            balance_operation_for_action(receivable_action),
            due_total,
            0,
        )
        connector_data.append(
            (
                receivable_account, receivable_action, due_total,
                receivable_account.opening_balance, None, None, None,
            )
        )

    # --- Discount and shipping --------------------------------------------
    # A discount given is contra-revenue, not an expense: it reduces what was
    # earned, and carries a DEBIT balance inside the income section. Shipping
    # charged to the customer is revenue, distinct from the freight EXPENSE
    # accounts, which are what the company pays out.
    discount_amount = resolve_discount_amount_for(sale)
    shipping_fee = quantize_money(sale.shipping_fee or 0)

    if discount_amount:
        account = control.get("Sales Discounts")
        if account is None:
            logger.error(
                "sale %s: discount of %s cannot be journaled -- company %s has no "
                "Sales Discounts account. The entry will not balance.",
                sale.pk, discount_amount, company.pk,
            )
        else:
            discount_action = action_for_side(
                account.kind, JournalEntryConnectorKindChoices.DEBIT
            )
            update_opening_balance(
                account,
                balance_operation_for_action(discount_action),
                discount_amount,
                0,
            )
            connector_data.append(
                (
                    account, discount_action, discount_amount,
                    account.opening_balance, None, None, None,
                )
            )

    if shipping_fee:
        account = control.get("Shipping Income")
        if account is None:
            logger.error(
                "sale %s: shipping fee of %s cannot be journaled -- company %s has "
                "no Shipping Income account. The entry will not balance.",
                sale.pk, shipping_fee, company.pk,
            )
        else:
            shipping_action = action_for_side(
                account.kind, JournalEntryConnectorKindChoices.CREDIT
            )
            update_opening_balance(
                account,
                balance_operation_for_action(shipping_action),
                shipping_fee,
                0,
            )
            connector_data.append(
                (
                    account, shipping_action, shipping_fee,
                    account.opening_balance, None, None, None,
                )
            )

    # --- Deposit -----------------------------------------------------------
    deposit = quantize_money(sale.deposit or 0)
    if deposit:
        if direction == SaleReceptKindChoices.REFUND:
            account = sale.payable_charter_account
            deposit_side = JournalEntryConnectorKindChoices.CREDIT
        else:
            account = sale.receivable_charter_account
            deposit_side = JournalEntryConnectorKindChoices.DEBIT
        if account is None:
            logger.error(
                "sale %s: deposit of %s cannot be journaled -- no charter account "
                "on the document. The entry will not balance.", sale.pk, deposit,
            )
        else:
            # Both charter accounts are picked on the document and neither is
            # necessarily an asset -- a refund paid onto a credit card is a
            # liability, on which the old literal landed the opposite side.
            deposit_action = action_for_side(account.kind, deposit_side)
            update_opening_balance(
                account, balance_operation_for_action(deposit_action), deposit, 0
            )
            connector_data.append(
                (
                    account, deposit_action, deposit,
                    account.opening_balance, None, None, None,
                )
            )

    # --- Tax ---------------------------------------------------------------
    _post_tax_legs(sale, lines, direction, connector_data)

    # --- The entry ---------------------------------------------------------
    undeposited = get_chart_of_account(["Undeposited Funds"], company).get(
        "Undeposited Funds"
    )
    is_deposit = bool(
        sale.receivable_charter_account_id
        and undeposited is not None
        and sale.receivable_charter_account_id == undeposited.pk
    )

    if direction == SaleReceptKindChoices.REFUND:
        kind = JournalEntryKindChoices.REFUND_RECEIPT
    elif sale.is_invoice:
        kind = JournalEntryKindChoices.SALE
    else:
        kind = JournalEntryKindChoices.SALE_RECEPT

    total = quantize_money(sale.total or 0)
    journal_entry = JournalEntryService.create_journal_entry(
        amount=total,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=kind,
        is_transaction=True,
        is_journal_entry=True,
        is_deposit=is_deposit,
        company=company,
        object=sale,
    )

    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=total,
        request_kind=request_kind,
        journal_entry=journal_entry,
        customer=sale.customer,
        created_by=created_by or sale.created_by,
    )

    _log_balance(sale, journal_entry)
    return journal_entry


def _log_balance(sale, journal_entry):
    """Report whether the entry we just wrote actually balances.

    Cheap, and the only thing that turns a silent structural imbalance into
    something greppable in production.
    """
    rows = journal_entry.journalentryconnector_set.all()
    debit = sum(Decimal(r.debit or 0) for r in rows)
    credit = sum(Decimal(r.credit or 0) for r in rows)
    if debit != credit:
        logger.error(
            "sale %s: journal entry %s does NOT balance -- debit %s vs credit %s "
            "(out by %s) across %s lines",
            sale.pk, journal_entry.pk, debit, credit, debit - credit, len(rows),
        )
    else:
        logger.info(
            "sale %s: journal entry %s balances at %s across %s lines",
            sale.pk, journal_entry.pk, debit, len(rows),
        )


def reconcile_sale_items(sale, sales_items, *, product_for):
    """Make the document's persisted lines match the submitted payload.

    Returns a summary dict.

    The missing half of amendment. `update()` only ever walked the submitted
    list -- updating a line that carried a uid, inserting one that did not --
    and never looked at what was already on the document. A line the user
    deleted in the grid was simply never visited, so its row survived, kept
    rendering on the invoice, and kept its revenue, its cost of sales and its
    inventory relief in the ledger, while the header total was written down
    without it. A two-line invoice with the second line removed was left
    overstating revenue by that line's value and reporting goods as sold that
    nobody was billed for.

    Lines that disappear from the payload are marked REMOVED rather than
    deleted: `sale_lines()` already excludes them, so they stop posting, while
    the row and its history stay put. Deleting would take the journal
    connectors that reference it with it.

    `product_for` resolves a payload entry to a Product, so this helper stays
    free of serializer-layer lookups.
    """
    summary = {"updated": 0, "created": 0, "removed": 0}
    if sales_items is None:
        return summary

    surviving = set()

    for payload in sales_items:
        uid = payload.get("uid")
        if uid:
            item = sale.saleitem_set.filter(uid=uid).first()
            if item is None:
                logger.warning(
                    "sale %s: payload names line %s, which is not on this "
                    "document -- ignored", sale.pk, uid,
                )
                continue
            _apply_line_payload(item, payload, product_for(payload))
            item.save()
            summary["updated"] += 1
        else:
            item = SaleItem(sale=sale, status=SaleItemStatusChoices.PUBLISHED)
            _apply_line_payload(item, payload, product_for(payload))
            item.save()
            summary["created"] += 1
        surviving.add(item.pk)

    stale = sale.saleitem_set.exclude(pk__in=surviving).exclude(
        status=SaleItemStatusChoices.REMOVED
    )
    summary["removed"] = stale.count()
    if summary["removed"]:
        logger.info(
            "sale %s: %s line(s) dropped from the payload -- marking REMOVED so "
            "the repost stops recognising them", sale.pk, summary["removed"],
        )
        stale.update(status=SaleItemStatusChoices.REMOVED)

    return summary


def _apply_line_payload(item, payload, product):
    """Absolute assignment from a payload entry onto a line.

    Absolute, not delta: the repost recomputes everything from the result, so
    the line only has to end up describing what the user submitted.
    """
    if product is not None:
        item.product = product
    for field in ("section", "note", "description", "status"):
        if field in payload:
            setattr(item, field, payload[field])
    if "quantity" in payload:
        item.quantity = payload["quantity"] or 0
    if "total" in payload:
        item.total = payload["total"] or 0
    if "sale_price" in payload:
        item.sale_price = payload["sale_price"] or 0
    for field in ("refund_quantity", "refund_status", "refund_total"):
        if field in payload:
            setattr(item, field, payload[field])
    if "is_tax" in payload or "is_item_tax" in payload:
        item.is_tax = payload.get("is_tax", payload.get("is_item_tax", item.is_tax))

    if "tax_uid" in payload:
        tax_uid = payload.get("tax_uid")
        if tax_uid:
            from agencyio.models import AgencyTax
            # Scoped through the line's own sale. This resolved on `uid` alone,
            # so an amend could attach another tenant's tax to a line, and the
            # repost would then book this sale's tax into their liability
            # account by way of `tax_group.sales_tax_account`. `.first()` rather
            # than `get_object_or_404`, so a uid the company does not own now
            # leaves the tax unchanged instead of silently retargeting it.
            tax = AgencyTax.objects.filter(
                uid=tax_uid, company=item.sale.company
            ).first()
            if tax is not None and tax.pk != item.tax_id:
                item.tax = tax
                # The rate this line was filed at belonged to the old tax; a
                # different one has to be snapshotted afresh on the next post.
                item.tax_snapshot = None
        else:
            item.tax = None
            item.tax_snapshot = None


def void_sale_postings(sale, *, created_by=None, restore_inventory=True):
    """Reverse a posted document by POSTING a reversal, not by erasing it.

    Returns the reversing `JournalEntry`, or None if there was nothing posted.

    Deliberately different from `reverse_sale_postings()`. An amendment deletes
    its journal because it writes a replacement in the same transaction, so the
    intermediate state is never a thing anyone can observe. A void has no
    replacement: the document was issued, someone was given it, and the books
    have to show that it was issued and then reversed. Erasing the entry is what
    made deleted sales impossible to reconstruct -- `JournalEntry.sale` is
    CASCADE, so deleting the row took the entry and every one of its lines with
    it while leaving every `opening_balance` they had moved exactly where it
    was. There was then no record of what the document had posted, so the drift
    could not even be measured, let alone replayed.

    The original entry is left alone. The reversal is a second entry whose lines
    are the originals with their sides flipped, marked DELETED, so the pair nets
    to zero and both remain readable.
    """
    from common.django_rest.helpers.balance_helpers import (
        action_for_side,
        balance_operation_for_action,
    )
    from common.django_rest.helpers.id_generator import get_unique_id

    entries = list(JournalEntry.objects.filter(sale=sale))
    if not entries:
        logger.info("void_sale_postings: sale %s had nothing posted", sale.pk)
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

        # Flip the side this line posted on, then move the stored balance the
        # matching way, so the two cannot disagree.
        original_action = action_for_side(account.kind, original.kind)
        opposite = "substraction" if original_action == "addition" else "addition"
        update_opening_balance(
            account, balance_operation_for_action(opposite), amount, 0
        )
        connector_data.append(
            (
                account, opposite, amount, account.opening_balance, None,
                original.saleitem, original.purchase_item,
            )
        )

    _reverse_customer_balance(sale)

    if restore_inventory:
        restore_sale_inventory(sale)

    template = entries[0]
    reversal = JournalEntry.objects.create(
        entry_number=get_unique_id(
            JournalEntry, sale.company_id, "entry_number", "JE"
        ),
        amount=template.amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=template.kind,
        is_transaction=True,
        is_journal_entry=True,
        is_deposit=template.is_deposit,
        company=sale.company,
        sale=sale,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=template.amount,
        request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
        journal_entry=reversal,
        customer=sale.customer,
        created_by=created_by or sale.created_by,
    )

    logger.info(
        "void_sale_postings: sale %s reversed by entry %s with %s line(s)",
        sale.pk, reversal.pk, len(connector_data),
    )
    return reversal


def recalculate_sale_totals(sale):
    """Bring the header back in line with the lines that survive.

    Only for callers that remove a line without supplying replacement totals --
    the DELETE endpoint for a single line. Everywhere else the client sends
    `total` and `due_total` in the payload and those win; this must not
    second-guess them.

    Without it that endpoint is guaranteed to leave the document inconsistent:
    the lines shrink, the header does not, and A/R is debited for goods that are
    no longer on the invoice. Deleting one line of a two-line invoice used to
    leave the whole original revenue posted -- the per-line unwind was gated on
    `is_sale_receipt`, so for an invoice it did nothing at all -- while hard
    deleting the row, which is why it could not be reconstructed afterwards.

    The relationship reproduced here is the one the documents already satisfy:

        total     = sum of the live lines
        due_total = total + tax - discount + shipping - deposit

    with tax added only when it is EXCLUSIVE, because inclusive tax is already
    inside the line prices. `total_tax` is recomputed from the lines' own rates,
    except on documents whose tax comes from an `auto_sales_tax` breakdown --
    that is the client's figure to own, and there is no per-line rate to derive
    it from.
    """
    lines = list(sale_lines(sale))
    total = sum(quantize_money(line.total or 0) for line in lines) or Decimal("0.00")

    fields = ["total", "due_total", "updated_at"]
    sale.total = total

    uses_auto_tax = bool((sale.auto_sales_tax or {}).get("breakdown"))
    if not uses_auto_tax:
        recomputed_tax = Decimal("0.00")
        for line in lines:
            base = quantize_money(line.total or 0)
            for _account, rate in resolve_line_taxes(line):
                recomputed_tax += quantize_money(base * rate / Decimal("100"))
        sale.total_tax = recomputed_tax
        fields.append("total_tax")

    tax = quantize_money(sale.total_tax or 0)
    if sale.tax_kind != TaxKindChoices.EXCLUSIVE:
        # Inclusive tax already sits inside the line prices, and NO_TAX has none.
        tax = Decimal("0.00")

    due = (
        total
        + tax
        - resolve_discount_amount_for(sale)
        + quantize_money(sale.shipping_fee or 0)
        - quantize_money(sale.deposit or 0)
    )
    sale.due_total = due if due > 0 else Decimal("0.00")
    sale.save(update_fields=fields)

    logger.info(
        "recalculate_sale_totals: sale %s -> total=%s tax=%s due_total=%s "
        "across %s live line(s)",
        sale.pk, sale.total, sale.total_tax, sale.due_total, len(lines),
    )
    return sale
