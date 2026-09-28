# Inventory Valuation Detail — Implementation Notes

**Status: DEFERRED.** A faithful report cannot be built from the current data
model. It requires new infrastructure (an append-only inventory-movement
ledger). This note records why, so the feasibility work isn't repeated.

Pairs with `Inventory_Valuation_Detail_Report_Documentation.md` (the spec). The
**Inventory Valuation Summary** (shipped, `/api/v1/we/reports/inventory-valuation-summary`)
already covers the ending quantity + value per item.

---

## What the report requires
A per-item, **date-ordered ledger** of every inventory movement (starting value,
bill/check/expense, vendor credit incl. value-only Qty-0 lines, invoice/sales-receipt,
credit-memo/refund, quantity adjustments), each line showing Qty, FIFO Rate,
Inventory cost, and the **running** Qty-on-hand and Asset value after it — ending
equal to the Summary and reconciling to the Balance Sheet Inventory Asset.

To produce running balances you must **replay every movement in date order**. The
data needed for that replay is not preserved (below).

## Why it's blocked (current data model)
1. **Original purchase quantities are destroyed.** FIFO sale relief mutates
   `PurchaseItem.quantity` in place (`common/django_rest/helpers/fifo_product_quantity_helpers.py:45-46`),
   and `PurchaseItem.opening_quantity` is *also* mutated by customer credit notes
   (`weapi/django_rest/serializers/creditnotes.py:445`). There is no original/
   remaining split, so a consumed layer only shows its current remainder.
2. **No stock-movement / FIFO-layer ledger exists.** The per-sale layer
   consumption (`deduction_details`) is computed in memory at sale time
   (`weapi/django_rest/serializers/sales.py:500-599`) and discarded.
3. **No `django-simple-history`** on `Product`/`PurchaseItem` (only on `companyio`
   models), so prior quantities aren't queryable.
4. **The journal ledger is not a sufficient substitute.** `journalio.JournalEntryConnector`
   records the dollar movements + links to `saleitem`/`purchase_item`/`credit_note_item`
   + dates, but: it stores **no per-line quantity**; it is **not append-only**
   (sale edit/delete physically `.delete()` the asset/COGS lines —
   `weapi/django_rest/views/sales.py:392-507`); **stock-adjustment connector lines
   carry no product/`StockAdjustmentItem` FK** (`weapi/django_rest/serializers/stock.py:192-244`),
   so they can't be attributed per product; and costing is a **hybrid** (true FIFO
   on sales via `purchase_item.purchase_price`, but average/standard cost on
   adjustments and credit notes).
5. **It wouldn't tie to the Summary anyway.** The Summary is a non-FIFO
   `quantity × single ProductAdditionalCost.amount` snapshot, explicitly "FIFO
   valuation out of scope." A true FIFO-replayed Detail total would only equal it
   by coincidence (single cost layer, no price changes).

Net: original quantities are gone, layer-consumption isn't recorded, and the one
ledger-like store (journal connectors) is editable, qty-less, and partly
unattributable. A correct Detail ledger **cannot be derived** from this.

## Prerequisite to make it feasible
Add an **append-only `InventoryMovement`** (stock-ledger) model, written by every
inventory-affecting path:
- Fields: `company`, `product`, `date` (source-document date), source ref
  (transaction type + uid), `quantity` (signed), `rate`/`unit_cost`,
  `inventory_cost` (signed), and running `qty_on_hand` / `asset_value`.
- Write a movement row at: purchase create (bill/check/expense), **each FIFO
  layer relieved on a sale**, vendor credit, credit memo/refund, stock
  adjustment, and product starting value.
- **Never edit in place** — post reversing entries instead of deleting, so the
  ledger stays auditable and replayable.

Then the Detail report is a straight grouped read of this ledger, and a correct
historical *as-of* Summary also becomes possible.

**Caveat:** pre-ledger history cannot be backfilled faithfully (the source data is
already mutated); a backfill can only seed a single current opening snapshot per
item, with the true line-by-line history accruing from the ledger's start date.

## Effort
Large and invasive — touches every inventory write path, needs a migration and
careful tests, and changes the sale/credit/adjustment serializers. Recommend
scoping it as its own project rather than folding it into a report task.

---
*Investigated 2026-06-29 via a 3-agent feasibility workflow; verdict: not
reconstructable without the ledger above.*
