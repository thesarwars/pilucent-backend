# Recurring Transactions (Bill + Expense + Cheque + Estimate) — Frontend Integration

What the frontend needs to build the Recurring Transactions screens against the
Phase 1 backend. Pairs with the four specs in this folder
(`Balanzify_Recurring_Transactions_Bill.md`, `Balanzify_Recurring_Transactions_Expense.md`,
`Balanzify_Recurring_Transactions_Cheque.docx`, `Balanzify_Recurring_Transactions_Estimate.md`).

All four transaction types — **Bill**, **Expense**, **Cheque**, and **Estimate** —
share one template model, one endpoint, and one scheduling engine; they differ
only in what they post and which fields apply (see §4).

The first three are **money-out** (purchases addressed to a vendor). **Estimate**
is the odd one out: it's a **sales-side, customer-facing, non-posting** quote — it
names a **customer** (not a vendor), writes no journal entry, and only affects the
books later if it's converted to an invoice (conversion is out of Phase 1 scope).

**Phase 1 scope.** The backend ships the *template library* and the *Use* action
(create a real bill/expense/cheque/estimate now from a template). The **background
Generation Job, reminders queue, autopay execution, the cheque print queue, and
the estimate email/status/conversion lifecycle are NOT built yet** — see §10 so
the UI doesn't promise behavior the backend doesn't do yet.

---

## 1. Endpoints

Base: `/api/v1/we/recurring-templates` (the "we" workspace API). Everything is
company-scoped to the workspace JWT (`company_id` claim).

| Action | Method + path |
|---|---|
| List templates | `GET /api/v1/we/recurring-templates` |
| Create template | `POST /api/v1/we/recurring-templates` |
| Retrieve one | `GET /api/v1/we/recurring-templates/{uid}` |
| Update (full) | `PUT /api/v1/we/recurring-templates/{uid}` |
| Update (partial) | `PATCH /api/v1/we/recurring-templates/{uid}` |
| Delete (soft) | `DELETE /api/v1/we/recurring-templates/{uid}` |
| Duplicate | `POST /api/v1/we/recurring-templates/{uid}/duplicate` |
| Use (generate now) | `POST /api/v1/we/recurring-templates/{uid}/use` |

`{uid}` is the template's UUID (the `uid` field, not a numeric id).

### Auth & gating

- **Plan feature:** requires the `is_expense` plan flag (same gate as one-off
  bills/expenses). A `403` with a subscription message means the plan doesn't
  include it.
- **Role permission:** standard model permissions via the workspace role system
  — `view_recurringtemplate` (GET), `add_recurringtemplate` (POST incl.
  duplicate/use), `change_recurringtemplate` (PUT/PATCH), `delete_recurringtemplate`
  (DELETE). Company admins bypass the check. A `403` "role doesn't have power"
  means the user's role lacks the permission.

Bill, Expense, Cheque, and Estimate templates all live on the **same** endpoint;
they differ only by `txn_type` (`BILL` / `EXPENSE` / `CHEQUE` / `ESTIMATE`).

---

## 2. List (`GET /recurring-templates`)

Paginated (DRF `PageNumberPagination`):

```jsonc
{
  "count": 12,
  "next": "…?page=2",
  "previous": null,
  "results": [ /* slim rows, see below */ ]
}
```

Page size defaults to 10; override with `?limit=` (max 100) and `?page=`.

### Query params

| Param | Meaning |
|---|---|
| `txn_type` | Filter: `BILL`, `EXPENSE`, `CHEQUE`, or `ESTIMATE`. |
| `template_type` | Filter: `SCHEDULED`, `REMINDER`, `UNSCHEDULED`. |
| `status` | Filter: `ACTIVE`, `ENDED`. (Soft-deleted `REMOVED` rows are never returned.) |
| `search` | Case-insensitive partial match on template name, vendor display name, **and** customer display name (so estimate rows match their customer too). |
| `ordering` | One of `created_at`, `next_run_date`, `name`, `total_amount` (prefix `-` for desc, e.g. `-next_run_date`). |

### Slim row shape (list only)

```jsonc
{
  "uid": "…",
  "name": "Monthly Rent",
  "txn_type": "BILL",
  "template_type": "SCHEDULED",
  "status": "ACTIVE",
  "currency_code": "USD",
  "total_amount": "1000.000",
  "autopay_enabled": false,
  "supplier_name": "Landlord LLC",       // vendor/payee (null for ESTIMATE)
  "customer_name": null,                 // customer (set only for ESTIMATE)
  "party_name": "Landlord LLC",          // the counterparty: customer for ESTIMATE, else vendor — use this for the "party" column
  "interval_display": "Every month on day 1",  // ready-to-print schedule label
  "previous_run_date": null,             // last produced occurrence; null until first run
  "next_run_date": "2026-08-01",         // next due date; null for Unscheduled/Ended
  "line_count": 2,
  "created_at": "2026-07-02T…Z"
}
```

`interval_display` is a human string built by the backend (e.g. `"Unscheduled"`,
`"Every 2 weeks on Mon"`, `"Every 3 months on day 15"`, `"Every month on the last Fri"`).
Use it directly for the Interval column.

---

## 3. Create / Retrieve / Update (the full template)

`POST` and `GET/PUT/PATCH /{uid}` use the full serializer. Relations are sent
and returned as **`uid` strings** (not numeric ids) — **except `warehouse` and
`payment_method`, which are written as uid strings but read back as
`{ "uid": "…", "title": "…" }` objects** (`null` when unset).

### Header fields

| Field | Type | Notes |
|---|---|---|
| `name` | string(≤100) | Required. |
| `txn_type` | enum | `BILL` (default), `EXPENSE`, `CHEQUE`, or `ESTIMATE`. |
| `template_type` | enum | `SCHEDULED` (default), `REMINDER`, `UNSCHEDULED`. |
| `mailing_address` | text | Money-out: vendor mailing address. **Estimate: doubles as the customer billing address.** |
| `memo` | text | Copied to each generated transaction (estimate: the description/statement memo). |
| `autopay_enabled` | bool | Stored only (autopay execution not built yet). |
| `currency_code` | char(3) | Default `"USD"`. |
| `create_days_in_advance` | int | Scheduled: create N days early. Stored (job not built). |
| `remind_days_before` | int | Reminder templates: remind N days before. Stored (job not built). |
| `supplier` | uid | Vendor/payee. **Required for `BILL`/`EXPENSE`/`CHEQUE`**; not used for `ESTIMATE`. |
| `customer` | uid | Quote recipient. **Required for `ESTIMATE`**; not used for money-out types. |
| `terms` | uid | Payment terms → drives generated **bill** due date. Bill only. |
| `warehouse` | uid | Optional. Bill only. Write a uid string; reads back as `{uid, title}` or `null`. |
| `payment_account` | uid | The account money is paid from. **Required for `EXPENSE` and `CHEQUE`**, ignored for `BILL`. For `EXPENSE` it's a bank **or** credit-card account; for `CHEQUE` it's the **bank (cash)** account the cheque is drawn on. |
| `payment_method` | uid | Optional (Expense). Write a uid string; reads back as `{uid, title}` or `null`. |
| `cheque_number` | string(≤50) | Cheque only. The cheque number, or a label like `"EFT"`. Leave blank to defer (see `print_later`). |
| `print_later` | bool | Cheque only. When `true`, the cheque is queued for batch printing and its number is assigned at print time (so `cheque_number` is recorded blank on generate). Default `false`. |
| `permit_number` | string(≤100) | Cheque only. Optional reference/permit carried onto the cheque. |
| `email_to` | text | Estimate only. Comma-separated recipient email(s). **Stored, not yet wired** — on Use the estimate emails the customer's own email (see §10). |
| `email_cc` / `email_bcc` | text | Estimate only. Optional extra recipients. Stored, not yet wired. |
| `auto_email` | bool | Estimate only. Auto-email on scheduled generation. Stored (job not built). Default `false`. |
| `message_on_estimate` | text | Estimate only. Customer-facing message. Stored (Phase 1 uses `memo` as the estimate description). |

### Schedule fields (embedded; required for SCHEDULED/REMINDER)

| Field | Type | Notes |
|---|---|---|
| `frequency` | enum | `DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`. Required unless `UNSCHEDULED`. |
| `interval_count` | int ≥1 | The "every N" multiplier (default 1). |
| `day_mode` | enum | `DAY_OF_MONTH` or `WEEKDAY` (monthly/yearly). |
| `day_of_month` | int 1–31 | Day-of-month rule. **Clamps** to the last valid day in shorter months (31 → Feb 28/29) without changing the rule. |
| `weekday` | int **0–6** | **0 = Monday … 6 = Sunday.** Used by weekly and by monthly/yearly `WEEKDAY` mode. |
| `ordinal` | enum | `FIRST`, `SECOND`, `THIRD`, `FOURTH`, `LAST` (which weekday-of-month). |
| `month_of_year` | int 1–12 | Yearly only. |
| `start_date` | date | First date considered. Required unless `UNSCHEDULED`. |
| `end_type` | enum | `NONE` (default), `BY_DATE`, `AFTER_COUNT`. |
| `end_date` | date | Required when `end_type = BY_DATE`. |
| `end_after_occurrences` | int | Required when `end_type = AFTER_COUNT`. |

### Lines (`lines`: array, at least one)

Two kinds, distinguished by `line_type`:

```jsonc
// CATEGORY line — charges an account (rent, utilities, fees)
{
  "line_type": "CATEGORY",
  "charter_account": "<account-uid>",   // REQUIRED for CATEGORY
  "amount": "1000.00",
  "description": "Office rent",
  "is_billable": false,
  "tax": "<tax-uid>",                    // optional
  "customer": "<customer-uid>",          // optional (billable/job tracking)
  "position": 0                          // optional display order
}

// ITEM line — a catalog product/service
{
  "line_type": "ITEM",
  "product": "<product-uid>",            // REQUIRED for ITEM
  "quantity": "5",
  "rate": "10.00",
  "amount": "50.00",                     // send Qty × Rate
  "description": "Widget",
  "is_billable": false,
  "tax": "<tax-uid>",
  "customer": "<customer-uid>"
}
```

On update, **`lines` fully replaces** the existing lines (send the complete
set). Omitting `lines` in a `PATCH` leaves them unchanged.

### Read-only / computed fields (returned, don't send)

| Field | Meaning |
|---|---|
| `uid` | Template id. |
| `status` | `ACTIVE` / `ENDED` / `REMOVED`. Set via delete, not writable. |
| `total_amount` | Cached sum of line amounts **+ tax**, recomputed on every save. |
| `next_run_date` | First/next occurrence, computed from the schedule on save. `null` for Unscheduled. |
| `previous_run_date`, `occurrences_generated` | Run state (advances in Phase 2). |
| `supplier_name`, `payment_account_title`, `interval_display` | Display helpers. |
| Each line's `charter_account_title`, `product_title`, `customer_name` | Display helpers. |
| `created_at`, `updated_at` | Timestamps. |

### Which fields apply per template type

| Type | Schedule block | `create_days_in_advance` | `remind_days_before` |
|---|---|---|---|
| `SCHEDULED` | Required | shown | — |
| `REMINDER` | Required | — | shown |
| `UNSCHEDULED` | Hidden (no `frequency`/`start_date`) | — | — |

For `UNSCHEDULED`, `next_run_date` is always `null` and the row has no timetable.

---

## 4. Bill vs Expense vs Cheque vs Estimate — the key differences

| | **Bill** (`BILL`) | **Expense** (`EXPENSE`) | **Cheque** (`CHEQUE`) | **Estimate** (`ESTIMATE`) |
|---|---|---|---|---|
| Side | Money-out (purchase) | Money-out | Money-out | **Money-in (sales)** |
| Meaning | Money **owed** (posts to A/P) | Money **already paid** | Paid **by cheque** on a bank account | A **quote** to a customer — **non-posting** |
| Party | `supplier` (vendor) | `supplier` | `supplier` | **`customer`** (no supplier) |
| `payment_account` | Not used | **Required** — bank/CC | **Required** — bank (cash) only | Not used |
| `terms` / due date | Used | Not used | Not used | Not used |
| Type-specific fields | — | — | `cheque_number`, `print_later`, `permit_number` | `email_to/cc/bcc`, `auto_email`, `message_on_estimate` |
| Generated record | A Bill (posts to A/P) | An Expense | A Cheque (bank register; numbered) | An Estimate (a **non-posting** Sale; no GL/inventory/tax) |

Form behavior by type:
- **Bill** — show Terms/Warehouse + vendor; hide Payment account, cheque, estimate fields.
- **Expense** — show vendor + Payment account (bank or CC); hide Terms + cheque + estimate fields.
- **Cheque** — show vendor + Payment account **filtered to bank accounts only** + the
  cheque number/print-later/permit fields; hide Terms + estimate fields.
- **Estimate** — show **customer** (not vendor) + email/message fields; hide Terms,
  Payment account, cheque fields. It quotes a customer and posts nothing.

For Cheque, the `payment_account` picker must list **only bank (cash) accounts** —
a cheque cannot be drawn on a credit card. (The backend accepts any account uid;
enforce the bank-only filter in the UI.)

---

## 5. Row actions

### Duplicate — `POST /{uid}/duplicate`

No body. Returns a new independent template (full shape) named `"Copy of …"`,
`status=ACTIVE`, with empty run history (`previous_run_date=null`,
`occurrences_generated=0`) and a freshly computed `next_run_date`. `201`.

### Use — `POST /{uid}/use`

Creates a **real** bill / expense / cheque / estimate from the template *right
now* and returns a summary. This is the primary action for Unscheduled templates
and the on-demand action for Scheduled/Reminder. (An **estimate** created this
way is non-posting — it just records the quote; nothing hits the ledger.)

Request body (all optional):

```jsonc
{
  "bill_date": "2026-07-02",   // the transaction date; defaults to today.
                               //   The field is named bill_date for every type — it's the
                               //   expense date / cheque date / estimate (quote) date too.
  "send_email": false          // email a copy (bill emails the vendor; estimate emails the customer)
}
```

Response — **Bill**:

```jsonc
{
  "detail": "Bill created from template.",
  "template_uid": "…",
  "txn_type": "BILL",
  "bill_uid": "…",             // the created Purchase uid
  "purchase_id": "PUR-000123",
  "bill_date": "2026-07-02",
  "due_date": "2026-07-17",    // from terms, or null
  "total": "1000.000",
  "total_tax": "0.000",
  "due_total": "1000.000"
}
```

Response — **Expense**:

```jsonc
{
  "detail": "Expense created from template.",
  "template_uid": "…",
  "txn_type": "EXPENSE",
  "expense_uid": "…",          // the created Expense uid
  "date": "2026-07-02",
  "total": "99.000",
  "total_tax": "9.900"
}
```

Response — **Cheque**:

```jsonc
{
  "detail": "Cheque created from template.",
  "template_uid": "…",
  "txn_type": "CHEQUE",
  "cheque_uid": "…",           // the created Purchase (cheque) uid
  "purchase_id": "PUR-000124",
  "cheque_number": "1005",     // "" when print_later (assigned at print time)
  "date": "2026-07-02",
  "total": "1200.000",
  "total_tax": "0.000",
  "print_later": true
}
```

Response — **Estimate**:

```jsonc
{
  "detail": "Estimate created from template.",
  "template_uid": "…",
  "txn_type": "ESTIMATE",
  "estimate_uid": "…",         // the created Sale (estimate) uid
  "estimate_id": "EST-000045", // the estimate/tracking number
  "reference_number": "EST-000045",
  "date": "2026-08-01",
  "expiry_date": null,         // not set in Phase 1 (no template expiry field)
  "total": "2000.000",
  "total_tax": "160.000"
}
```

Branch on `txn_type` (or on which `*_uid` is present) to decide where to
deep-link (the created bill / expense / cheque register / estimate). The three
money-out types post to the ledger immediately; the **estimate posts nothing**
(it starts life as an open quote). For a cheque with `print_later: true`, tell
the user it's been queued for printing (the print queue itself is Phase 2).

**Note (Phase 1):** Use does **not** advance the template's schedule or write a
run-history entry; the template stays available and `next_run_date` is
unchanged. Using the same template twice on the same day creates two separate
transactions (that's intended for on-demand use).

### Delete — `DELETE /{uid}`

**Soft delete.** Sets `status = REMOVED` and clears `next_run_date`. The
template disappears from the list; already-generated bills/expenses/cheques/
estimates are untouched. Returns `204`.

---

## 6. Validation errors (`400`)

Field-keyed messages, standard DRF shape (`{ "field": ["message"] }`):

| Field | When |
|---|---|
| `lines` | Empty list; or a `CATEGORY` line missing `charter_account`; or an `ITEM` line missing `product`. |
| `frequency` | Scheduled/Reminder without a frequency. |
| `start_date` | Scheduled/Reminder without a start date. |
| `end_date` | `end_type = BY_DATE` without an end date. |
| `end_after_occurrences` | `end_type = AFTER_COUNT` without a count. |
| `payment_account` | `txn_type = EXPENSE` without a payment account, or `txn_type = CHEQUE` without a bank account. |
| `supplier` | Missing on a money-out type (`BILL`/`EXPENSE`/`CHEQUE`). |
| `customer` | Missing on an `ESTIMATE`. |

---

## 7. Money & formatting notes

- All money fields are decimal **strings** (e.g. `"1000.000"`). Header/line
  amounts use 3 decimal places; line `quantity`/`rate` use 4. Parse as decimal,
  don't use JS floats for math.
- `total_amount` is server-computed (lines + tax). The UI's live total is a
  preview; the persisted value comes back on save — reconcile to it.
- Weekday is **0=Mon … 6=Sun** (differs from JS `Date.getDay()` where 0=Sun).
  Convert when mapping to/from a day picker.

---

## 8. Suggested build order

1. **List + filters** (`GET`) — render the table using `interval_display`,
   `supplier_name`, `total_amount`, `next_run_date`, `status`.
2. **Create/Edit form** — header + schedule block + lines; switch the
   type-specific fields by `txn_type` (Terms for Bill; Payment account for
   Expense; bank account + cheque number/print-later/permit for Cheque;
   **customer + email/message for Estimate**); switch the party field between
   vendor (money-out) and customer (Estimate); switch the schedule block by
   `template_type`.
3. **Row actions** — Duplicate, Use (with the result deep-link), Delete.
4. **Retrieve** for the edit/prefill screen.

---

## 9. "Make recurring" from an existing transaction (optional)

The spec's "Make recurring" convenience is a frontend prefill: read the existing
bill / expense / cheque / estimate, map its party (vendor **or** customer for an
estimate) + lines + memo into a new-template draft, let the user add the
schedule, then `POST` it as a normal create. No dedicated backend endpoint is
needed.

---

## 10. Not built yet (Phase 2+) — don't promise these

- **Automatic generation.** Scheduled templates are **not** auto-posted by a job
  yet; `next_run_date` is informational. Bills/expenses only appear when a user
  hits **Use**.
- **Reminders List.** No reminders queue endpoint yet; `remind_days_before` is
  stored only.
- **Autopay execution.** `autopay_enabled` is stored but never acted on.
- **Run history / occurrences.** The occurrence ledger exists in the schema but
  isn't surfaced via API yet.
- **Cheque print queue & auto-numbering.** Cheque templates store `cheque_number`
  and `print_later`, but there is **no Print Cheques queue endpoint** and **no
  automatic next-number assignment** yet. On Use, the cheque records with the
  template's `cheque_number` as-is (blank when `print_later`); it does not pull
  the next number from the bank account's sequence. Outstanding-cheque /
  reconciliation behavior is the existing one-off cheque behavior — nothing
  recurring-specific is added here in Phase 1.
- **Estimate email, status lifecycle & conversion.** The estimate email fields
  (`email_to/cc/bcc`, `auto_email`) and `message_on_estimate` are **stored but
  not wired** — on Use, the estimate is created and (if `send_email`) emailed to
  the **customer's own email**, not `email_to`. There are **no** endpoints yet
  for the estimate status lifecycle (Sent/Accepted/Declined/Expired), for
  **converting** an estimate to an invoice/sales receipt (the posting step), or
  for **expiry** — generated estimates get `expiry_date = null` (the template has
  no expiry/valid-days field in Phase 1). Discount, shipping, tax-automation, and
  online-payment options from the spec are not implemented; the estimate total is
  simply lines + line tax.

Design these screens so they degrade gracefully (e.g. show `next_run_date` as
"next due" without implying auto-posting; treat estimates as non-posting quotes
with no conversion action yet) until Phase 2 lands.
