# Data Migration — Estimates

## Overview

The Estimates data migration allows bulk import of sales estimates (quotes) from an external CSV/spreadsheet into the system. Estimates are **non-posting transactions** — they generate no journal entries, no GL balance changes, and no FIFO inventory movements. They are purely informational Sales records with `is_estimated=True`.

---

## Architecture

The estimate migration follows the standard multi-handler data migration pipeline:

```
CSV Upload → Field Mapping → Validate → Review Impact → Confirm Import → (Rollback)
```

Each stage is handled by a dedicated service class:

| Stage | Class | File |
|---|---|---|
| Handler registration | `EstimateMigrationHandler` | `handlers/estimates.py` |
| Validation | `EstimateValidatorService` | `services/estimate_validator.py` |
| Impact preview | `EstimateImpactService` | `services/estimate_impact.py` |
| Import | `EstimateMigrationImporter` + `MigrationEstimateCreateService` | `services/estimate_importer.py` |
| Rollback | `EstimateMigrationRollbackService` | `services/estimate_rollback.py` |
| Async task | `process_estimate_migration` | `tasks.py` |

---

## Step-by-Step Flow

### 1. Handler Registration

`EstimateMigrationHandler` registers itself via `@MigrationHandlerRegistry.register`. Key flags:

- `data_type = "estimates"` — identifies this handler in the registry
- `has_gl_impact = False` — signals no accounting impact
- `is_posting_transaction = False` — no journal entries will be created

The handler defines a `COLUMN_ALIAS_MAP` that maps flexible user-facing column names (e.g. `"estimate #"`, `"qty"`, `"rate"`) to internal canonical field names (e.g. `estimate_number`, `quantity`, `unit_price`).

**Required fields** (will error if missing): `estimate_number`, `estimate_date`, `line_amount`, `customer` or `customer_email`.

---

### 2. Validation (`EstimateValidatorService.validate_job`)

Runs on every `DataMigrationRow` for the job. For each row:

1. **Field mapping** — `FieldMapperService.apply_mapping_to_row` converts raw CSV columns to canonical names using `COLUMN_ALIAS_MAP`.
2. **Customer resolution** — looks up by email first, then by display name / company name / first+last name split. Must be active (not `REMOVED`) and company-scoped. Unresolved customer → `ERROR`.
3. **Estimate number** — required, must be non-empty. → `ERROR` if missing.
4. **Date parsing** — `estimate_date` required; `expiry_date` optional but warned if present and invalid or before `estimate_date`.
5. **Amount validation** — `line_amount` required, must be numeric, must be ≥ 0. Qty × unit price mismatch with amount → `WARNING`.
6. **Product resolution** — optional, but warns if product has no income account (since estimates have no GL impact, this is a warning only, not an error).
7. **Income account override** — if provided, resolves from Chart of Accounts. Unresolved → `ERROR`.
8. **Tax** — optional, warning if not found.
9. **Warehouse/Location** — optional, warning if not found.
10. **Payment term** — optional, warning if not found.
11. **Duplicate check** — checks `Sale` records with `is_estimated=True` for the same customer + estimate number (by `invoice_id`, `tracking_number`, or `reference_number`). Behavior depends on `job.duplicate_handling`:
    - `SKIP_DUPLICATES` → row status becomes `SKIPPED`.

Row status summary:

| Condition | Row Status |
|---|---|
| All checks pass | `READY` |
| Only warnings | `WARNING` |
| Any error | `ERROR` |
| Duplicate (skip policy) | `SKIPPED` |

After all rows are processed, job counters (`ready_rows`, `warning_rows`, `error_rows`, `duplicate_rows`, `skipped_rows`) are updated and job status moves to `VALIDATED → REVIEW_IMPACT`.

---

### 3. Impact Preview (`EstimateImpactService.generate`)

Groups rows by `customer_uid::estimate_number` and creates one `DataMigrationImpactLine` per estimate group. Since there is no GL impact:

- `debit = 0`, `credit = 0`
- `account_title = "No Accounting Impact"`
- `transaction_type = "estimate_summary"`
- `report_impact = "Sales Estimates Report"` (informational only)

The response to the frontend explicitly states:
> "Estimates have no accounting impact. No journal entries, no balance updates, and no tax postings will be created."

Job status moves to `IMPACT_REVIEWED → CONFIRM_IMPORT`.

---

### 4. Import (`EstimateMigrationImporter.run` + `MigrationEstimateCreateService.create_estimate`)

Triggered via `confirm_import`. In production, dispatched as a Celery task (`process_estimate_migration`); in `DEBUG` mode, runs synchronously.

**Grouping:** Rows are grouped by `customer_uid::estimate_number` — each group becomes one `Sale` record with multiple `SaleItem` rows.

**Per-group processing (inside `transaction.atomic`):**

1. Re-resolves customer from DB (safety check).
2. Re-checks for duplicates at import time (race condition guard).
3. Aggregates estimate-level fields (date, currency, addresses, term, memo) from the first row that provides each field.
4. Builds `estimate_lines` list from all rows in the group (one line per CSV row).
5. Calls `MigrationEstimateCreateService.create_estimate`:
   - Creates `Sale` with `is_estimated=True`, `is_invoice=False`, `is_sale_receipt=False`.
   - Sets `expired_date` (not `due_date`) from `expiry_date`.
   - Generates a unique `tracking_number` prefixed `"EST"` via `get_unique_id`.
   - Stores the original `estimate_number` as `reference_number`.
   - Creates `TermConnector`, `CurrencyConnector`, `AddressConnector` records.
   - Bulk-creates `SaleItem` records for each line.
   - **No** journal entries, **no** FIFO deductions, **no** opening balance updates.
6. Marks all rows in the group as `IMPORTED` with `linked_record_uid` = `sale.uid`, `linked_record_type = "sale"`.

**Job final status:**

| Outcome | Job Status |
|---|---|
| All estimates imported | `COMPLETED` |
| Some imported, some failed | `PARTIALLY_COMPLETED` |
| All failed | `FAILED` |

---

### 5. Rollback (`EstimateMigrationRollbackService.run`)

Available when job status is `COMPLETED`, `PARTIALLY_COMPLETED`, or `PARTIALLY_ROLLED_BACK`.

For each imported row with a `linked_record_uid`:

1. Fetches the `Sale` record (`is_estimated=True`, company-scoped).
2. **Simply deletes** the `Sale`. No reversal journals, no opening balance adjustments — because estimates have no accounting side effects.
3. Django CASCADE automatically removes `SaleItem`, `AddressConnector`, `CurrencyConnector`, `TermConnector`.
4. Marks rows as `ROLLED_BACK`, clears `linked_record_uid`.

Rows whose Sale no longer exists are immediately marked `ROLLED_BACK` (idempotent).

**Job final status:**

| Outcome | Job Status |
|---|---|
| All rolled back, none remaining | `ROLLED_BACK` |
| Partial failures | `PARTIALLY_ROLLED_BACK` |

---

## Key Design Decisions

- **No GL impact** is the defining characteristic. Every service class explicitly documents this — validator warns (not errors) on missing income account; importer skips all journal/balance/FIFO logic; rollback does a straight delete with no reversal entries.
- **Rows = lines, not headers.** Each CSV row is a line item. Multiple rows sharing the same customer + estimate number are grouped into a single `Sale` at import time.
- **Duplicate guard runs twice** — once at validation time and again inside the atomic block at import time to handle race conditions.
- **`reference_number` preserves origin.** The system-generated `tracking_number` is the live identifier; the user's original estimate number is stored as `reference_number` for traceability.
- **Celery vs. synchronous.** In production (with `CELERY_BROKER_URL` set and `DEBUG=False`) the import runs as a Celery task. In dev/debug mode it runs synchronously via `.apply()`.

---

## CSV Template

| Column | Required | Notes |
|---|---|---|
| Customer Name | Yes* | Matched by display name, company name, or first+last |
| Customer Email | Yes* | *Either name or email required |
| Estimate Number | Yes | Stored as `reference_number`; unique per customer |
| Estimate Date | Yes | Format set on the job (e.g. MM/DD/YYYY) |
| Expiry Date | No | Warning if before estimate date |
| Product Name | No | Warning if not found |
| Description | No | Per-line description |
| Quantity | No | Warning if ≤ 0 or inconsistent with unit price × amount |
| Unit Price | No | |
| Amount | Yes | Per-line total; must be ≥ 0 |
| Tax Code | No | Warning if not found |
| Account Name | No | Overrides product's income account |
| Location | No | Warehouse/location; warning if not found |
| Currency | No | Defaults to company currency |
| Currency Rate | No | Defaults to 1 |
| Memo | No | Stored as `Sale.description` |
| Billing Address | No | |
| Shipping Address | No | |
| Shipping By | No | |
| Shipping Date | No | |
| Term | No | Payment term; warning if not found |
| Reference Number | No | Additional reference (separate from estimate number) |
