# Inventory & Sales-Tax Reports — Frontend Integration

What the frontend needs to render the reports built after the aging set. Pairs
with `ap_ar_frontend.md` (the A/P & A/R aging reports) and the four specs:
`Inventory_Valuation_Summary`, `Inventory_Valuation_Detail`,
`Taxable_Sales_Summary`, `Sales_Tax_Liability`.

---

## 1. The endpoints

Base: `/api/v1/we/reports` (admin/"we" API). All are `GET`, company-scoped to the
workspace JWT (`company_id` claim), and require the `view_reports` permission + the
`is_standard_report` plan feature (same gating as every other report).

| Report | Endpoint | Period? | Shape |
|---|---|---|---|
| Inventory Valuation Summary | `GET /api/v1/we/reports/inventory-valuation-summary` | No (snapshot, as of today) | one row per item |
| Inventory Valuation Detail | `GET /api/v1/we/reports/inventory-valuation-detail` | Yes (`end_date` = as-of) | per-item transaction ledger |
| Taxable Sales Summary | `GET /api/v1/we/reports/taxable-sales-summary` | Yes (accrual) | items grouped by category |
| Sales Tax Liability | `GET /api/v1/we/reports/sales-tax-liability` | Yes (accrual) | agency → rate components |

Every endpoint has three response modes:
- **default** — the full report JSON (below);
- **`?keywords=overview`** — totals only (for a header tile);
- **`?is_pdf=true`** — renders a PDF, returns `{ "file_uid": "…", "url": "…" }`.

For the two sales-tax reports, **`start_date` / `end_date`** (`YYYY-MM-DD`) set the
filing period (accrual basis); they apply independently (a one-sided range is
honored as open-ended), and the as-of label = `end_date` or today. Inventory
Valuation **Detail** takes **`end_date`** (or `date_before`) as an as-of date
(default today). Inventory Valuation **Summary** ignores dates — it is always a
current snapshot.

> **PDF caveat:** generating any report PDF currently clears the company's other
> report PDFs server-side, so treat the returned `url` as the only retained one.

---

## 2. Inventory Valuation Summary

On-hand inventory valued at cost: one row per inventory item, plus a weighted total.

```jsonc
{
  "as_of": "2026-06-24",
  "rows": [
    {
      "uid": "…",
      "product": "Air Pod 3nd Gen",   // item name
      "sku": "",                        // "" if none
      "quantity": 572.0,
      "asset_value": 228950.00,         // cost value of on-hand units
      "calc_avg": 400.26                // asset_value / quantity (avg unit cost)
    }
    // …
  ],
  "total": { "quantity": 671.0, "asset_value": 327950.00, "calc_avg": 488.75 }
}
```

**Rendering**: a matrix — Item / SKU / Qty / Asset Value / Calc. Avg, then a bold
TOTAL row. Show Qty and money with 2 decimals; the total's Asset Value and Calc.
Avg carry the currency symbol. The **total `calc_avg` is a weighted blend**
(`total.asset_value / total.quantity`), *not* the average of the per-row averages —
display it as given. `overview` mode returns `{ "as_of", "total" }`.

---

## 3. Inventory Valuation Detail

A transaction-by-transaction ledger per inventory item — the opening balance plus
every purchase/sale/return/adjustment — with the running quantity-on-hand and
asset value after each line. Grouped by product, subtotal per item, grand total.

```jsonc
{
  "as_of": "2026-07-06",
  "groups": [
    {
      "uid": "…",                          // product uid
      "product": "Air Pod 3nd Gen",
      "sku": "",
      "rows": [
        {
          "uid": "…",                      // movement uid
          "date": "2026-01-01",
          "transaction_type": "Opening balance",  // ready-to-display label
          "type": "OPENING",               // raw enum: OPENING / PURCHASE / SALE /
                                           //   SALE_RETURN / PURCHASE_RETURN /
                                           //   ADJUSTMENT_IN / ADJUSTMENT_OUT / REVERSAL
          "quantity": 10.0,                // SIGNED: + in, − out
          "rate": 400.00,                  // per-unit cost; null if none
          "inventory_cost": 4000.00,       // signed cost moved (COGS negative on sales)
          "running_quantity": 10.0,        // on-hand AFTER this line
          "running_value": 4000.00         // asset value AFTER this line
        }
        // … movements oldest-first within the item
      ],
      "subtotal": { "quantity": 8.0, "inventory_cost": 3600.00, "asset_value": 3600.00 }
    }
    // … one group per product
  ],
  "total": { "asset_value": 327950.00 }    // grand total ending asset value
}
```

**Rendering** (per group): a product header (name + SKU), then the `rows` —
Date / Transaction type / Qty / Rate / Inventory cost / Qty on hand / Asset value
(`date`, `transaction_type`, `quantity`, `rate`, `inventory_cost`,
`running_quantity`, `running_value`) — then a bold **"Total for {product}"** row
(the `subtotal`), and finally a grand **TOTAL** (`total.asset_value`). Notes:
- `quantity` is **signed** — negative = stock out (sale/return); render with a −.
- `rate` may be **null** (movements with no unit rate) → show "—".
- `running_quantity` / `running_value` are computed **server-side** (cumulated in
  date order), so a backdated bill/sale sorts into place — just display them.
- Date control → send **`end_date=YYYY-MM-DD`** for an as-of valuation (default today).
- `overview` mode returns `{ "as_of", "total" }`; `is_pdf=true` returns `{ file_uid, url }`.
- Items with no movements don't appear.

---

## 4. Taxable Sales Summary

The taxable sales **base** (the amount tax is charged on — **not** the tax itself),
grouped by product/service.

```jsonc
{
  "as_of": "2026-06-24",
  "no_item":  { "amount": -20.00 },     // the unlabeled bucket (null if none)
  "items": [                            // uncategorized items, sorted by name
    { "uid": "…", "label": "Air Pod 3nd Gen", "amount": 65500.00 },
    { "uid": "…", "label": "Galaxy S25 Ultra 256GB", "amount": 26000.00 }
  ],
  "categories": [                       // each category with its own subtotal
    {
      "label": "Gadget",
      "amount": 100.00,                 // category subtotal
      "items": [ { "uid": "…", "label": "Air Pod 2nd Gen (deleted)", "amount": 100.00 } ]
    }
  ],
  "total": 91580.00                     // filing-ready taxable base
}
```

**Rendering** (top → bottom): the `no_item` row (blank label) if present, then the
uncategorized `items`, then each `categories` group (its `items` indented + a "Total
for {label}" subtotal), then a bold **TOTAL**. Notes:
- Amounts are the **ex-tax** line totals; credit memos / refund receipts / discounts
  make a row (or the no-item bucket) **negative** — render with a leading minus.
- **Deleted products** still appear, with "(deleted)" already in the `label`.
- `overview` mode returns `{ "as_of", "total" }`.
- This is the *base*, not the tax — for tax collected use the Sales Tax Liability report.

---

## 5. Sales Tax Liability

Tax owed, grouped by **tax agency**, broken into the **rate components** (state /
county / city / district) that make up each agency.

```jsonc
{
  "as_of": "2026-06-24",
  "agencies": [
    {
      "agency_uid": "…",
      "agency": "New York Department of Taxation and Finance",
      "rows": [                                   // one row per rate component
        { "name": "New York State",          "gross_total": 2600.00, "non_taxable": 500.00, "taxable_amount": 2100.00,  "tax_amount": 83.99 },
        { "name": "New York, New York City", "gross_total": 2600.00, "non_taxable": 500.00, "taxable_amount": 2100.00,  "tax_amount": 102.38 },
        { "name": "Sales Tax",               "gross_total": 20000.00,"non_taxable": 0.00,   "taxable_amount": 20000.00, "tax_amount": 2000.00 }
      ],
      "tax_total": 2186.37                        // agency total = sum of Tax Amount ONLY
    }
    // … California agency, tax_total 4331.25
  ],
  "total": 6517.62                                // period liability = sum of agency totals
}
```

**Rendering**: group by agency (header), then component rows with the four money
columns (Gross / Non-taxable / Taxable / Tax), then a bold **"Total for {agency}"**
row that fills **only the Tax column** (leave Gross/Non-taxable/Taxable blank on the
total row). Critical: **do not sum Gross/Taxable across an agency's rows** — the same
sale is taxed by several overlapping component rates, so those columns repeat the same
base and summing them multi-counts; only `tax_amount` is additive. Agencies with no
activity in the period are omitted. `overview` mode returns `{ "as_of", "total" }`
(the period liability across agencies; each agency is filed separately).

---

## 6. Formatting

Thousands separators + 2 decimals (e.g. `49,331.25`). Convention: **grand/agency
totals carry the currency symbol** (`$327,950.00`), body figures are plain; negatives
with a leading minus (optionally red/parentheses). All money values are JSON numbers,
already rounded to 2 dp server-side.

---

## 7. Caveats worth surfacing (tooltips / disclaimers)

- **Inventory Valuation Summary** is a **current snapshot** (as of today), valued at
  `quantity × unit cost` (ties to the dashboard inventory-value card). Historical
  as-of valuation isn't supported here — use the Detail report's `end_date` for that.
- **Inventory Valuation Detail** reads an append-only stock-movement ledger that
  begins at the **opening-balance seed** (run once at rollout). So each item's first
  line is its **OPENING** balance and genuine history starts there. Purchases and
  sales (invoices/receipts) post to the ledger going forward; **edits, deletes,
  returns, and stock adjustments are not wired in yet** (Phase 2), so those movement
  types won't appear as lines until then. Surface a note like *"History from
  {opening date}; opening balance shown as the first line."* Running balances are
  derived server-side in date order, so they stay correct even for backdated documents.
- **Sales-tax reports are accrual-basis only** (by `Sale`/`CreditNote` date). Cash basis
  isn't derivable from the data; don't offer a cash toggle for these yet.
- **Sales Tax Liability tax = `taxable × rate/100`** on the period base. The filed
  return can differ by a cent or two because tax is rounded per transaction at sale
  time — present it as "computed" and let users reconcile to the actual remittance.
- **Taxable Sales Summary** assumes line amounts are ex-tax (true for exclusive-tax
  setups). The taxable base should reconcile to the taxable amount on the Sales Tax
  Liability report and to `Taxable + Non-taxable = Total Sales`.
- Both sales-tax reports tie to the books' Sales Tax Payable but, like the aging
  reports vs the Balance Sheet, can diverge from the GL (manual journal entries, status
  edits) — surface the same "run for the same period/basis" reconciliation guidance.
