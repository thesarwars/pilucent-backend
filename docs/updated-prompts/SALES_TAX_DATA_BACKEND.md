# Sales Tax — Data Contract (Backend)

**Goal:** define exactly what data the **Sales tax** screen
(`/dashboard/taxes/sales`) needs, **from what accounting perspective it must be
computed**, and the precise response shape for the two endpoints that feed it.

The frontend is built; this document is the backend half. The screen already
calls two endpoints (`GET /we/agencies`, `GET /we/agencies/{uid}/tax-tracker`).
This spec locks their shapes and fixes the one thing the frontend currently does
wrong (it hard-codes a 5% rate — see §7).

---

## 1. The perspective — read this first

Everything on this screen answers ONE question:

> "For **this taxing agency**, in **this filing period**, how much sales tax did
> the company **collect from customers** and therefore **owe to the agency** —
> measured on the agency's **reporting basis**?"

That single sentence pins down four perspective decisions the backend must make.
Get these wrong and every number on the page is wrong.

### 1.1 It is about SALES the company MADE, not purchases

Sales tax owed = tax the company **charged customers** on **taxable sales** and
now holds in trust to remit. Source documents are the company's **sales**
records only:

- Sales invoices, sales receipts / cash sales, POS sales.
- **Credit memos / refunds / returns REDUCE** the taxable base and the tax owed
  for the period they fall in (negative contribution).

Purchases, bills, expenses, and use-tax are **out of scope** for this screen.

### 1.2 It is scoped **company → agency → period**

- One row of data = one **(company, agency, filing period)**.
- An **agency** is a single taxing jurisdiction the company is registered with
  (e.g. "New York State DTF", "Texas Comptroller"). It owns: a **rate** (or set
  of rates), a **filing frequency**, a **reporting basis**, and a **period
  calendar**.
- A sale contributes to an agency only when that sale is **sourced to that
  agency's jurisdiction** (destination/origin sourcing per the agency's rules).
  A company selling into 3 states → 3 agencies → 3 independent sets of figures.

### 1.3 The reporting **basis** (accrual vs cash) — the critical axis

The badge on the hero reads **`ACCRUAL · LIVE`** — that is
`agency.reporting_method`. The **same invoices produce different period totals**
depending on basis, so the backend MUST compute both the overview and the
tracker **on the agency's configured basis**:

| Basis | A sale counts in the period of… | Taxable base = |
|---|---|---|
| **ACCRUAL** | the **invoice / document date** (when the sale occurred), regardless of payment | tax on all taxable sales **dated** in the period |
| **CASH** | the **payment received date** | tax on the taxable portion of **payments collected** in the period |

Consequences the backend must handle:
- **Cash basis + partial payment:** only the **collected fraction** of an
  invoice's tax counts, in the period money arrived. A 50%-paid invoice
  contributes 50% of its tax.
- **Cash basis + unpaid invoice:** contributes **nothing** until paid.
- **Accrual basis:** payment state is irrelevant; the invoice date decides.

`reporting_method` is per-agency and authoritative. The frontend does not
recompute basis — it displays whatever the backend returns.

### 1.4 Taxable vs non-taxable vs gross

Every sale line is classified, and the three overview figures are sums of those
classifications **within the period, on the basis above**:

- **Taxable sale** — line is subject to tax at a positive rate in this
  jurisdiction. Drives the tax owed.
- **Non-taxable sale** — **exempt** (customer/product exemption certificate),
  **zero-rated**, or **out-of-scope** for this jurisdiction. Included in gross,
  contributes **$0** tax.
- **Gross sale** = `taxable + non_taxable`. (Definitionally consistent — the
  frontend shows share-of-gross percentages, so these three MUST reconcile:
  `total_gross_sale == total_taxable_sale + total_non_taxable_sale`.)

Classification source of truth: the **product/service tax code** on each line ×
the **customer's exemption status** × the **agency's jurisdiction rules**. This
is a backend responsibility; the frontend never classifies.

---

## 2. Entities & the screen that consumes them

| Screen element | Fed by | Field(s) |
|---|---|---|
| Agency selector (pill dropdown) | `GET /we/agencies` | `uid`, `title`, `state`, `status` |
| Hero: "Sales tax owed" + basis badge | agency `sale_overview` + `reporting_method` | `tax_owed`, `reporting_method` |
| Hero: period progress "Day 8 of 31", "Period ends …" | agency period metadata | `start_of_period`, `date`, `filling_frequency` |
| Tile: Taxable sales | `sale_overview.total_taxable_sale` | + share of gross |
| Tile: Non-taxable sales | `sale_overview.total_non_taxable_sale` | + share of gross |
| Tile: Tax owed this period | `sale_overview.tax_owed` | (see §7) |
| Hint strip: "Gross sales $X this period" | `sale_overview.total_gross_sale` | |
| Filing-periods table | `GET /we/agencies/{uid}/tax-tracker` | `year_to_date_data[]` |

---

## 3. Endpoint 1 — Agencies + current-period overview

`GET /we/agencies`

Returns the company's registered agencies. **Each agency carries a
`sale_overview` computed for that agency's CURRENT OPEN filing period, on its
reporting basis.**

```jsonc
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "agc_...",
      "title": "New York State DTF",
      "state": "NY",                       // 2-letter; null for non-geographic agencies
      "status": "ACTIVE",                  // ACTIVE | INACTIVE | ...
      "reporting_method": "ACCRUAL",       // ACCRUAL | CASH  → drives the whole overview
      "filling_frequency": "MONTHLY",      // MONTHLY | QUARTERLY | ANNUAL | WEEKLY  (note existing spelling)
      "start_of_period": "Apr 1, 2026",    // human label of the current period start
      "date": "2026-04-30",                // current period END date (ISO) — "Period ends"
      "sale_overview": {
        "total_taxable_sale": 0.0,         // taxable base in the current period, on basis
        "total_non_taxable_sale": 0.0,     // exempt + zero-rated + out-of-scope
        "total_gross_sale": 0.0,           // MUST equal taxable + non_taxable
        "tax_owed": 0.0,                   // ← REQUIRED (see §7): tax on taxable base at agency rate(s)
        "combined_rate": 0.08              // ← REQUIRED: effective decimal rate used (e.g. 0.08 = 8%)
      }
    }
  ]
}
```

Rules:
- `sale_overview` is **always the current open period** for that agency
  (matches the hero + the three tiles, which have no period selector).
- All money is a **number** (not a string), same currency as the company.
- `total_gross_sale == total_taxable_sale + total_non_taxable_sale` (reconcile).
- `tax_owed` and `combined_rate` are **new required fields** — see §7.

---

## 4. Endpoint 2 — Per-period tax tracker (filing history)

`GET /we/agencies/{uid}/tax-tracker`

Returns each filing period for the agency in the year (the table, "latest
first" — the frontend reverses the array).

```jsonc
{
  "error": false,
  "message": "ok",
  "data": {
    "agency_name": "New York State DTF",
    "year_to_date_data": [
      {
        "month": "April",                  // full month name; used for the MON/YY chip + current-period detection
        "period": "Apr 1 – Apr 30, 2026",  // human period label
        "due_date": "May 20, 2026",        // filing/remittance due date (the 4-digit year is parsed out)
        "total_sales_amount": 0.0,         // gross sales in that period (on basis)
        "total_tax_amount": 0.0,           // tax owed/collected for that period (on basis)
        "status": "PENDING"                // see §6 — lifecycle
      }
    ]
  }
}
```

Rules:
- One entry **per filing period** in the fiscal year to date (monthly → up to 12
  rows, quarterly → up to 4, etc.), ordered oldest→newest (frontend reverses).
- `total_tax_amount` here is the **same definition** as `sale_overview.tax_owed`
  but for that specific (possibly closed) period. For the **current** period it
  should match the overview's `tax_owed`.
- The **current, still-open period** must be identifiable — the frontend flags
  it as "(Accruing)" by matching `month` to the current calendar month. Its
  `status` should be an accruing/open state, not a due/overdue one.

---

## 5. Period & due-date logic (backend owns this)

- **Period boundaries** come from `filling_frequency` + the agency's fiscal
  start. Monthly = calendar month; quarterly = 3-month blocks; annual = fiscal
  year. `start_of_period` / `date` describe the **current** period's start/end.
- **Progress bar** ("Day 8 of 31") is derived on the frontend from today's date
  vs the period length — no backend field needed, but `date` (period end) must
  be correct for "Period ends …".
- **`due_date`** per period is the statutory remittance deadline (e.g. NY
  monthly = 20th of the following month). Backend computes it per jurisdiction;
  the frontend only displays it and flags "· late" when status is overdue.

---

## 6. Status lifecycle (drives chips, filters, and the "File return" CTA)

The frontend maps `status` case-insensitively into these buckets — return
values that fall into exactly one:

| Backend `status` (examples) | UI chip | Bucket |
|---|---|---|
| `ACCRUING` / `OPEN` / `LIVE` | Accruing (violet) | current open period, not yet fileable |
| `PENDING` / `DUE` | Pending (warn) | period closed, return due, **needs filing** |
| `OVERDUE` / `LATE` | Overdue (danger) | past due date, **needs filing** — opens the "Record payment" flow |
| `PAID` / `FILED` | Paid (success) | settled |

Notes:
- **"Needs filing"** = status matches pending/due/overdue AND not paid. The
  header "N returns need your attention" and the "File return" button key off
  this — so a closed-but-unpaid period MUST carry a pending/overdue status, never
  an accruing one.
- **Overdue** specifically routes to the "Record payment" (`ReviewDueSalesTax`)
  modal; everything else opens the review (`ReviewOpenSalesTax`) modal. So the
  distinction between `PENDING` and `OVERDUE` must be real (compare `due_date` to
  today server-side).

---

## 7. The one bug to fix: rate must come from the backend

**Today the frontend computes `tax_owed = total_taxable_sale × 0.05`** — a
hard-coded 5%. This is wrong for every jurisdiction that isn't exactly 5% and
silently misstates the liability.

**Required change:** the backend computes the tax and returns it. The frontend
will stop multiplying by 0.05 and simply read `sale_overview.tax_owed`.

- `tax_owed` = tax on the period's **taxable base**, computed with the agency's
  **actual configured rate(s)** on the **reporting basis** (§1.3). If the agency
  has multiple component rates (state + county + city + special district), sum
  them — `tax_owed` is the **total remittable**, and `combined_rate` is the
  effective decimal rate (`tax_owed / total_taxable_sale`, guard divide-by-zero →
  `0`).
- Ideally also expose a breakdown for the filing detail modal (optional now,
  needed later):

```jsonc
"rate_breakdown": [
  { "name": "NY State",       "rate": 0.04,   "amount": 0.0 },
  { "name": "NYC Local",      "rate": 0.045,  "amount": 0.0 },
  { "name": "MCTD surcharge", "rate": 0.00375,"amount": 0.0 }
]
```

Same applies to `year_to_date_data[].total_tax_amount` — it is the agency-rate
tax for that period, **not** `sales × 0.05`.

---

## 8. Edge cases the backend must get right

- **Reconciliation:** `gross == taxable + non_taxable` in every `sale_overview`
  and (as `total_sales_amount` vs its taxable split) in every tracker row.
- **Refunds / credit memos:** reduce the taxable base and `tax_owed` of the
  period they belong to (by basis) — can push a period negative; return the real
  signed number.
- **Exempt customers:** their taxable-eligible lines move to
  `total_non_taxable_sale`, not taxable, and contribute $0 tax.
- **Cash basis partial payments:** allocate tax by the collected fraction, in the
  period collected (§1.3).
- **No sales yet:** return zeros (not nulls) so the tiles render `$0.00` and 0%
  shares — the current screenshot state.
- **Rounding:** round `tax_owed` to the currency's minor unit (2 dp) the same way
  the remittance is filed, so the tiles and the filed return match.

---

## 9. Summary of what backend must deliver

- [ ] `GET /we/agencies` → each agency's `sale_overview` for the **current open
      period**, computed on `reporting_method` (accrual/cash).
- [ ] Add **`tax_owed`** and **`combined_rate`** to `sale_overview` (kills the
      frontend's hard-coded 5%). Optional `rate_breakdown`.
- [ ] Guarantee `gross == taxable + non_taxable`.
- [ ] `GET /we/agencies/{uid}/tax-tracker` → one row per filing period, oldest→
      newest, with `total_tax_amount` at the agency's real rate on basis.
- [ ] Correct **period boundaries**, **due dates**, and a real **status**
      (accruing vs pending vs overdue vs paid) per §5–§6.
- [ ] Handle refunds, exemptions, cash-basis partials, and zero states (§8).

**Net:** the frontend renders; the backend decides the **perspective** — which
sales, which period, which basis, and the rate. Once `tax_owed`/`combined_rate`
land, the frontend drops the `× 0.05` and the page reflects the real liability.
