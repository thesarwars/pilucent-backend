# A/P & A/R Aging Reports — Frontend Integration

What the frontend needs to render the four aging reports. Pairs with the four
specs in this folder (`AP_Aging_Detail`, `AP_Aging_Summary`, `AR_Aging_Detail`,
`AR_Aging_Summary`).

---

## 1. The four endpoints

Base: `/api/v1/we/reports` (admin/"we" API). All four are `GET`, company-scoped to
the workspace JWT (`company_id` claim), and require the `view_reports` permission +
the `is_standard_report` plan feature (same gating as every other report).

| Report | Endpoint | Shape |
|---|---|---|
| A/P Aging Detail | `GET /api/v1/we/reports/ap-aging-detail` | bands of transactions |
| A/P Aging Summary | `GET /api/v1/we/reports/ap-aging-summary` | vendor × bucket matrix |
| A/R Aging Detail | `GET /api/v1/we/reports/ar-aging-detail` | bands of transactions |
| A/R Aging Summary | `GET /api/v1/we/reports/ar-aging-summary` | customer × bucket matrix |

A/P = what **you owe vendors** (bills + vendor credits). A/R = what **customers owe
you** (invoices + credit memos). The two sides are structurally identical; only the
party (vendor/customer) and transaction labels differ — see §7.

---

## 2. Query params (all four)

| Param | Meaning |
|---|---|
| `start_date`, `end_date` | `YYYY-MM-DD`. Optional. The **as-of date** used for aging is `end_date` (else today). When both are given, the range also bounds which transactions are in scope by document date. Omit both for the "All Dates, as of today" view. |
| `keywords=overview` | Return **totals only** (for a summary tile/header) — no rows. |
| `is_pdf=true` | Render the report to PDF; returns `{ "file_uid", "url" }` instead of data. |

Out-of-range/garbage dates are ignored (treated as absent), so a bad `end_date`
falls back to today rather than erroring.

Each endpoint therefore has **three response modes**: default JSON (full report),
`overview` (totals), and `is_pdf` (a file). Examples below show the default JSON.

---

## 3. Detail reports (ap-aging-detail / ar-aging-detail)

One row per open transaction, grouped into aging **bands**, each with a subtotal,
plus a grand total.

### Response

```jsonc
{
  "as_of": "2026-06-24",
  "bands": [                              // only non-empty bands, most-overdue first
    {
      "key": "90_plus",
      "label": "91 or more days past due",
      "count": 9,                          // rows in this band (for the "(9)" header)
      "rows": [ /* see row shape */ ],
      "subtotal": { "amount": 398490.00, "open_balance": 399640.00 }
    }
    // ... 61_90, 31_60, 1_30, current (whichever are non-empty)
  ],
  "total": { "amount": 399690.00, "open_balance": 400840.00 }
}
```

Band `key`s, most-overdue first (empty bands are omitted): `90_plus`, `61_90`,
`31_60`, `1_30`, `current`. The `label` is ready to print (e.g. `"Current"`,
`"1 - 30 days past due"`).

### Row shape

```jsonc
{
  "uid": "…",                  // the transaction uid (drill-down/links)
  "kind": "BILL",              // A/P: BILL | VENDOR_CREDIT ; A/R: INVOICE | CREDIT_MEMO
  "transaction_type": "Bill",  // display label: Bill / Vendor Credit / Invoice / Credit Memo
  "date": "2025-05-26",        // document date (ISO) or null
  "num": "#PUR-1042",          // document/reference number ("" if none)
  "vendor_display_name": "Binary Burst",   // A/R: "customer_display_name"
  "store_full_name": "",       // warehouse/location, "" if none
  "due_date": "2025-05-26",    // ISO or null (credits have none)
  "past_due": 394,             // days overdue (int) or null (not-yet-due => 0; credits => null)
  "amount": 12000.00,          // original value (+ for bill/invoice, − for credit)
  "open_balance": 12000.00     // still outstanding today (+/−)
}
```

> The **only A/P↔A/R field difference** in a row is `vendor_display_name` vs
> `customer_display_name`. Everything else is identical.

### Rendering
- Render each band as a group: shaded header `"{label} ({count})"`, then its rows,
  then a bold **"Total for {label}"** subtotal row. End with a bold **TOTAL** row
  from `total`.
- Rows arrive **pre-sorted** within a band (dated items oldest-due first, then
  no-due-date credits) — render in array order.
- `amount` = original value (unchanged by payments); `open_balance` = what's left.
  When the two grand totals differ, the gap is the payments/credits already applied.
- **Past due column:** the A/P Detail spec lists it as a default column; the A/R
  Detail spec treats it as opt-in. The JSON always includes `past_due` either way —
  show/hide the column per report (the PDF already follows this: A/P shows it, A/R
  hides it).

### `overview` mode
```jsonc
{ "as_of": "2026-06-24", "total": { "amount": 399690.00, "open_balance": 400840.00 } }
```

---

## 4. Summary reports (ap-aging-summary / ar-aging-summary)

One rolled-up row per party, open balance spread across aging **columns**, with a
bottom column-totals row and a grand total.

### Response

```jsonc
{
  "as_of": "2026-06-24",
  "buckets": [                             // column order, left to right
    { "key": "current", "label": "Current" },
    { "key": "1_30",    "label": "1 - 30" },
    { "key": "31_60",   "label": "31 - 60" },
    { "key": "61_90",   "label": "61 - 90" },
    { "key": "90_plus", "label": "91 and over" }
  ],
  "rows": [
    {
      "vendor_uid": "…",                   // A/R: "customer_uid"
      "vendor_display_name": "Unimart",    // A/R: "customer_display_name"
      "buckets": { "current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 395790.00 },
      "total": 395790.00
    }
    // ... one row per party, sorted A→Z by name
  ],
  "column_totals": { "current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 1200.00, "90_plus": 399640.00 },
  "total": 400840.00
}
```

### Rendering
- Build a matrix: first (unlabeled) column = party name; one column per `buckets`
  entry (use `buckets` for the header labels **and** the column order); a **Total**
  column on the right. Bottom row = `column_totals` + the bold grand `total`.
- Read each cell as `row.buckets[bucket.key]` and the footer as
  `column_totals[bucket.key]`.
- **Leave zero cells blank** (don't print `0.00`) so the eye lands on real balances.
- Rows come sorted by name; offer a sort control on the **Total** column.
- A party can carry amounts in several buckets at once (e.g. an overdue bill and a
  newer credit) — `total` nets them. Negative totals are unapplied credits/overpayments.
- **Cross-check:** Σ`column_totals` == Σ row `total`s == `total`. Useful as an
  integrity assertion in the UI.

### `overview` mode
```jsonc
{ "as_of": "2026-06-24", "column_totals": { … }, "total": 400840.00 }
```

---

## 5. PDF mode (all four)

`?is_pdf=true` returns:
```jsonc
{ "file_uid": "…", "url": "/media/reports/ap_aging_detail-….pdf" }
```
Open/download `url`. (Note: generating a report PDF clears the company's previous
report PDFs server-side, so treat `url` as the latest.)

---

## 6. Buckets, signs & formatting

- **Bucket keys are stable** across reports: `current`, `1_30`, `31_60`, `61_90`,
  `90_plus`. Labels differ slightly by report family — **use the `label`/`buckets`
  the API returns** rather than hardcoding (Detail bands say "91 or more days past
  due"; Summary columns say "91 and over").
- **Signs:** bills/invoices are **positive**; vendor credits/credit memos are
  **negative**. A negative party total means you hold a net credit / they overpaid.
- **Money:** thousands separators + 2 decimals (e.g. `49,331.25`). Convention is to
  show the **grand total with the currency symbol** (`$52,662.00`) and body figures
  plain; render negatives with a leading minus (optionally red/parentheses).
- All money values are JSON numbers (already rounded to 2 dp server-side).

---

## 7. A/P ↔ A/R field cheat sheet

| Concept | A/P (ap-aging-*) | A/R (ar-aging-*) |
|---|---|---|
| Party field (Detail row) | `vendor_display_name` | `customer_display_name` |
| Party fields (Summary row) | `vendor_uid`, `vendor_display_name` | `customer_uid`, `customer_display_name` |
| Positive transaction `kind` | `BILL` ("Bill") | `INVOICE` ("Invoice") |
| Negative transaction `kind` | `VENDOR_CREDIT` ("Vendor Credit") | `CREDIT_MEMO` ("Credit Memo") |
| `num` source | bill reference (`#PUR-…`) | invoice number / credit-note number |
| Past due column in PDF | shown (default) | hidden (opt-in; JSON still has `past_due`) |

Everything else — bands, buckets, subtotals, totals, query params, response
envelope — is identical between the two sides.

---

## 8. Reconciliation & caveats (good to surface in tooltips)

- **Detail ↔ Summary reconcile**: for the same date, a side's Detail grand
  `open_balance` equals its Summary grand `total`. Drill from a Summary cell into the
  Detail filtered to that party.
- **Open balance** is the live outstanding amount (stored `due_total`), so it ties to
  the dashboard A/P/A/R aging cards. It is **not guaranteed** to equal the GL-based
  Balance Sheet A/P/A/R line — those are a separate source and can drift (e.g. on the
  A/P side, bills settled via the separate "Pay Bills" flow reduce the GL but not the
  bill's open balance, so they still show here at full balance).
- **Fully settled items drop off** (open balance 0). **Credits with no due date** are
  aged by their own transaction date (so an old credit can land in `90_plus` with a
  blank due date).
- **Empty bands/cells are omitted/blank**, not zero — don't treat their absence as an
  error.
