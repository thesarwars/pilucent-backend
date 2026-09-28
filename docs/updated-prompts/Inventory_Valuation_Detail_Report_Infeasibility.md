# Why the Inventory Valuation **Detail** Report Can't Be Built (Yet)

**Verdict:** Not feasible on the current data model. The report's two defining
columns — *running quantity on hand* and *running asset value* after each
transaction — depend on per-movement history that the system **never records**.
On-hand quantity is a single number mutated in place, and there is no stock
movement ledger. The report is **not reconstructable retroactively**, but it **is
buildable going forward** once a movement ledger is added (§5).

This is a data-model gap, not a query gap. Verified against current code (paths
and line numbers below).

---

## 1. What the Detail report requires

Per the report doc, for each product, ordered by date, over its full history
("All Dates"):

| # | Requirement | Data it needs |
|---|---|---|
| R1 | A date-ordered ledger of **every** movement (purchase, sale, sale-return, purchase-return, adjustment) | One append-only, per-product row per stock event, with an event date |
| R2 | **Signed quantity** per movement (+in / −out) | A signed delta on each movement |
| R3 | **Rate** — per-unit cost on the line | Unit cost stored on every movement type, incl. adjustments |
| R4 | **Inventory cost / COGS** on outbound, via FIFO | The cost consumed by each outbound line, resolved layer-by-layer, stored on that line |
| R5 | **Running quantity on hand** after each movement | On-hand balance as-of each event (a snapshot, or a replayable opening + complete movement stream) |
| R6 | **Running asset value** after each movement | R5 × the cost of the units then on hand (remaining-layer costs as-of that date) |

---

## 2. The root cause

> On-hand quantity (and each purchase lot's *remaining* quantity) is a **single
> scalar mutated in place**, with the previous value overwritten, and there is
> **no append-only stock-movement ledger**. FIFO consumption is recorded only as
> **dollar** debit/credit rows in the double-entry journal — never as a
> signed-quantity + cost movement row, and with no consumed-quantity column.

Confirmed:

- `update_quantity()` does `object.quantity += … ; object.save_dirty_fields()`
  ([common/django_rest/helpers/quantity_helpers.py:8](common/django_rest/helpers/quantity_helpers.py#L8)) — in-place, prior value gone.
- FIFO deduction does `product.quantity -= …; product.save()`
  ([common/django_rest/helpers/fifo_product_quantity_helpers.py:68](common/django_rest/helpers/fifo_product_quantity_helpers.py#L68)).
- `Product.quantity` is a bare `PositiveIntegerField` with **no opening/starting
  quantity** to replay forward from ([productio/models.py:22](productio/models.py#L22)).
- A repo-wide search for `Stock*/Inventory*` × `Movement/Ledger/Layer/Consumption/History`
  models returns **nothing** — only `StockAlert`, `StockAdjustment`,
  `StockAdjustmentItem` exist ([stockio/models.py](stockio/models.py)).

---

## 3. Gap per requirement

Legend: **HARD** = the data was never recorded → unreconstructable. **PARTIAL** =
recoverable with effort/holes. **AWKWARD** = derivable, not a blocker.

- **R1 — unified movement ledger — HARD as a ledger.**
  No movement table. Movements survive only as heterogeneous document lines:
  purchases on `PurchaseItem` (date via `Purchase.date`), sales on `SaleItem`
  (date via `Sale.date`), manual adjustments on `StockAdjustmentItem` (date via
  `StockAdjustment.date`), returns split between `SaleItem.refund_quantity` and
  `CreditNoteItem`. You can `UNION` these into a pseudo-ledger, but: (a) **returns
  are an aggregate scalar** (`SaleItem.refund_quantity`) — multiple partial
  refunds collapse into one number, losing their individual dates/quantities; and
  (b) **edits delete-and-recreate** the lines/connectors, so a surviving row
  reflects the last edit, not the movement history.

- **R2 — signed quantity — AWKWARD.**
  No stored sign, but implied by the source (purchase = +, sale = −,
  `StockAdjustmentItem.kind` ADDITION/DEDUCTION, credit note = +). Derivable.

- **R3 — rate — PARTIAL; HARD for adjustments.**
  Purchases carry `purchase_price`; sales carry `sale_price` (the *selling* price,
  not a cost). **Adjustments carry no rate** — `stockio/models.py` literally has
  `# Removed purchase_price field`. An adjustment's cost impact was never recorded.

- **R4 — per-line FIFO COGS — PARTIAL, journal-only, with hard holes.**
  `SaleItem` has **no cost/COGS column** — only `sale_price`
  ([salesio/models.py:150](salesio/models.py#L150)). COGS lives only in the
  journal: `fifo_product_deduction` returns `[(purchase_item, qty, price), …]`
  and the sale poster writes `JournalEntryConnector` rows tagged with both
  `saleitem` and `purchase_item` FKs + `date`/`debit`/`credit`. So "sale line →
  lot consumed → dollars" is *partially* recoverable, but:
  - **No consumed-quantity column** — only dollars; qty must be inferred as
    `amount ÷ purchase_item.purchase_price`, which fails for zero-price lots.
  - **Fallback units are unattributed** — when layers are exhausted the helper
    appends `(None, qty, price)` → connector `purchase_item = None`.
  - **Optional accounts drop the row** — if the product has no COGS/asset account,
    no lot-tagged connector is written at all.
  - **CASCADE deletes** — `JournalEntryConnector.saleitem`/`.purchase_item` are
    `on_delete=CASCADE`; editing/re-saving a sale removes its connector rows, so
    the COGS history for edited lines is gone.

- **R5 — running on-hand — HARD (the root blocker).**
  On-hand is overwritten in place (§2); no before/after is persisted, and there's
  no recorded opening quantity to anchor a replay. The generic `auditlog` text
  diffs are not read for inventory and miss `QuerySet.update()/bulk_update`
  (no signal) — incomplete by construction. Running on-hand as-of a past date is
  not reconstructable.

- **R6 — running asset value — HARD.**
  Needs R5 × the cost of units then on hand. Both inputs are destroyed: on-hand is
  overwritten, and each lot's **remaining** quantity (`PurchaseItem.opening_quantity`)
  is a *running* counter mutated in place — decremented on sale, incremented on
  return — not an as-of snapshot. "What remained in each layer on date X" is
  unknowable.

---

## 4. Retroactive vs. going forward

**Retroactive (existing data): NO — not reliably.** The two columns that *define*
the report (R5 running on-hand, R6 running asset value) depend on snapshots that
were never written; `Product.quantity` and `PurchaseItem.quantity` hold only
*current* values. COGS-per-sale (R4) is only partially recoverable from the
journal, with the holes above. A best-effort forward replay from the earliest
document date won't tie out — no opening quantity, refunds aggregated,
`bulk_update` mutations invisible to the audit trail, edited/deleted lines.
**Approximate at best, not auditable — treat as unreconstructable for a
valuation-grade report.**

**Going forward: YES.** With an append-only movement ledger written at the
existing choke points (§5), R1–R6 all become directly queryable. No historical
backfill will be accurate; the ledger is trustworthy only from its deployment
date onward (optionally seeded with one `OPENING` movement per product from
today's `Product.quantity` and current layer state).

---

## 5. Minimal schema to make it feasible going forward

**`StockMovement`** — append-only, one row per stock event per product:

- `uid`, `company` FK, `product` FK, `warehouse` FK (nullable)
- `date` (DateField) + `created_at` (within-day ordering tiebreak)
- `movement_type` — PURCHASE / SALE / SALE_RETURN / PURCHASE_RETURN /
  ADJUSTMENT_IN / ADJUSTMENT_OUT / OPENING
- originating line — GenericFK, or explicit nullable FKs to
  `PurchaseItem` / `SaleItem` / `CreditNoteItem` / `StockAdjustmentItem`
- `signed_quantity` (+in / −out)
- `rate` (Decimal 19,3) — unit price on the source line
- `inventory_cost` (Decimal 19,3) — signed cost impact; **COGS on outbound**
- `running_quantity` — on-hand **after** this movement (immutable snapshot)
- `running_value` (Decimal 19,3) — asset value **after** this movement
- `created_by` FK

**`StockMovementLayerConsumption`** — true FIFO detail; one row per lot slice an
outbound movement consumes (supplies the consumed-qty column absent today):

- `movement` FK (the outbound `StockMovement`)
- `purchase_item` FK (lot consumed; nullable — flag when fallback)
- `quantity_consumed` (Decimal) — **the column missing today**
- `unit_cost` (Decimal 19,3), `cost_amount` (Decimal 19,3)

**Where the writes go — both choke points already exist, so this is localized (no
rewiring of the ~30 call sites):**

- **`update_quantity`** — every on-hand mutation already routes through here with
  `product` + operation + delta. After the in-place update, emit one
  `StockMovement` (`signed_quantity` = delta, `running_quantity` = post value).
  Captures purchases, adjustments, credit notes, refund add-backs, importer flows
  uniformly.
- **`fifo_product_deduction`** — it already yields
  `[(purchase_item, qty, price), …]` (incl. the `(None, …)` fallback). Write one
  `StockMovementLayerConsumption` per tuple and set the outbound movement's
  `inventory_cost = Σ price·qty`. This finally persists **consumed quantity per
  layer** (not just journal dollars) and makes COGS attributable even for
  zero-price/fallback units.

`running_value` = sum of remaining-layer costs after the movement (available in
the same pass), or `running_quantity` × weighted cost as a simpler approximation.

---

## 6. Why the **Summary** report works and Detail doesn't

The Summary report ([weapi/django_rest/helpers/reports/inventory_valuation_summary.py](weapi/django_rest/helpers/reports/inventory_valuation_summary.py))
needs only a **current snapshot**: `Product.quantity` as it stands × one
`ProductAdditionalCost` per product. No dates, no per-movement rows, no as-of
replay — its `as_of` is a **display label only** (the view defaults to
`date.today()`; the helper docstring says *"Historical as-of valuation … is not
yet supported"*, [inventory_valuation_summary.py:22-23](weapi/django_rest/helpers/reports/inventory_valuation_summary.py#L22)).
Summary is feasible precisely because it reads the two things the model *does*
store cleanly — current on-hand and a current unit cost.

Detail needs the two things the model does **not** store: per-movement history
with running quantity/value over time (R5/R6), destroyed by in-place mutation;
and per-line FIFO COGS as durable movement rows (R4), which exist only as journal
dollar-diffs with no consumed-qty column. Those are structural absences.

---

## 7. Recommendation

1. **Don't ship Detail against current data** — it can't produce auditable
   running balances and would mislead.
2. **Add the `StockMovement` (+ layer-consumption) ledger** at the two choke
   points above. It's a contained change and also unlocks: as-of Summary
   valuation, stock movement history, and stronger COGS/audit reporting.
3. **Seed an `OPENING` movement** per product at deployment from current on-hand
   + current layer state, so the ledger is complete from day one forward.
4. Build the Detail report as a straight read over the ledger once it exists.
   Historical periods before the ledger's start show only from the opening
   snapshot — label that boundary clearly.
