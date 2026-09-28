# Inventory Movement Ledger — status & remaining wiring

Backs the Inventory Valuation Detail report. See
`Inventory_Valuation_Detail_Report_Infeasibility.md` for why this ledger was
needed.

## Shipped (v1)

- **Models** `stockio.StockMovement` + `stockio.StockMovementLayerConsumption`
  (append-only; source-line FKs are `SET_NULL` so the ledger outlives the
  document; company-scoped + under the tenant RLS policy).
- **Service** `stockio/django_rest/services/stock_movement.py::record_stock_movement`
  — records the immutable *facts* of a movement (signed quantity, rate, signed
  `inventory_cost`) and persists per-lot FIFO consumption (incl. the
  layer-exhausted `is_fallback` slice). Running quantity/value are **derived at
  read time** by the report (cumulating in date order), NOT stored — so a
  backdated document sorts into place and can never corrupt a running balance.
  The write runs in its own savepoint so a ledger failure never poisons the
  caller's posting transaction.
- **OPENING seed** `manage.py seed_stock_opening_movements` — one OPENING
  movement per inventory product from current on-hand × latest cost; idempotent.
  **Run once at rollout** (and after legacy-product imports) so the perpetual is
  seeded and running balances tie out.
- **Report** `/api/v1/we/reports/inventory-valuation-detail` — grouped by
  product, per-item subtotal + grand total, `keywords=overview` and `is_pdf=true`
  like the summary report.
- **Wired write sites (create paths):**
  - PURCHASE create (bill/cheque) — `weapi/.../serializers/purchases.py` (after
    `update_quantity`, inbound + rate + lot link).
  - SALE create (invoice / sales-receipt) — `weapi/.../serializers/sales.py`
    (after `fifo_product_deduction`, outbound + FIFO layer consumption + COGS).
  - Both are **best-effort** (wrapped in try/except that logs and never breaks
    the money posting). `sale_item` FK is left null in v1 (movement still carries
    product/date/type/COGS/layers).

## Not yet wired (Phase 2) — from the write-site map

Each is an additive `record_stock_movement(...)` call at the site, using
**delta-capture** for the sign (`post − pre` of `Product.quantity`) and a
`REVERSAL` type for un-dos. Movement type in parens.

| Area | Sites | Notes |
|---|---|---|
| Purchase edit/delete | `purchases.py` update path (PURCHASE, delta); `views/purchases.py` item-delete (REVERSAL) | inverted `"update"` branch → delta-capture is mandatory |
| Purchase importers | bill/check/expense importers (PURCHASE) | `datamigrationio/.../*_importer.py`, iterate created items |
| Sale edit | `sales.py` increase (SALE) / decrease (REVERSAL) / new-item (SALE) | item already saved on edit → inline |
| Sale item / whole-sale delete | `views/sales.py` restock paths (REVERSAL) | rebuild layers from `JournalEntryConnector.purchase_item` |
| Sale importers | invoice / sales-receipt importers (SALE) | |
| Returns | refund receipt + credit-note restock (SALE_RETURN); purchase-return / vendor credit (PURCHASE_RETURN) | `sales.py`, `serializers/creditnotes.py` |
| Adjustments | `StockAdjustmentItem` ADDITION (ADJUSTMENT_IN) / DEDUCTION (ADJUSTMENT_OUT) | no per-line cost stored (stockio removed `purchase_price`) → value approximate; cost via `ProductAdditionalCost.amount` |
| New product w/ opening qty | product create (OPENING) | |
| Link sale_item FK | set `sale_item` on the create-path SALE movement after `bulk_create` | traceability + enables sale-line-delete reversal |

## Known gaps (deliberately silent — the live counter is also unchanged there)

Whole-Sale delete, SALE credit-note delete, adjustment edit/delete, product edit,
and the rollback services that touch only `PurchaseItem` lots (not
`Product.quantity`) — these don't move the live on-hand counter today, so the
ledger correctly stays silent and still reconciles. Handle when those business
behaviors are fixed.

## Report / rollout notes

- After deploy, run `seed_stock_opening_movements`. Until then the Detail report
  has no rows.
- Running balances are derived by cumulating the ledger in date order; they are
  exact only once a product's movements are all captured (v1 covers create;
  edits/returns are Phase 2). An `end_date` (or `date_before`) query param gives
  a historical as-of valuation.
- Frontend: see the earlier assessment — the report is a new read-only screen
  mirroring the existing report family; label the opening-balance boundary.
