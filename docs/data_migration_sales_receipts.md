# Data Migration — Sales Receipts

## Overview

The Sales Receipts data migration imports historical or external **cash-basis sale receipts** in bulk from CSV (or other supported upload formats). In this product, a sale receipt is a normal [`Sale`](../salesio/models.py) row with:

- `is_sale_receipt = True`
- `is_invoice = False`
- `kind = SALE` (standard receipt; refund receipts are not in scope for this migration)
- `status = PAID` (payment is treated as received at import time)

This migration is a **posting** flow: it updates chart-of-account opening balances, runs **FIFO** inventory deduction for stocked products, creates **`JournalEntry`** records with kind **`SALE_RECEPT`**, and credits the **deposit** account (the account money was deposited to — same role as `receivable_charter_account` on the WE API sale receipt serializer). It mirrors the invoice migration pattern, but uses a single receipt date, no A/R balance for the document total (`due_total = 0`), and deposit instead of Accounts Receivable.

For the generic HTTP workflow (endpoints, job lifecycle), see [DATA_MIGRATIONS_API.md](DATA_MIGRATIONS_API.md).

---

## High-level workflow

```text
Create job (data_type = sales_receipts)
    → Upload file
    → Map columns (auto-map + manual mapping)
    → Preview rows
    → Validate
    → Review impact (accounting preview)
    → Dry run / Reconciliation (optional)
    → Confirm import (Celery or synchronous in DEBUG)
    → Results / Audit
    → Rollback (if needed; completed or partially completed jobs)
```

```mermaid
flowchart LR
    subgraph pipeline [Migration pipeline]
        A[Upload] --> B[Map]
        B --> C[Validate]
        C --> D[Impact]
        D --> E[Import]
    end
    E --> F[Rollback optional]
```

---

## Architecture

| Stage | Class | File |
|--------|--------|------|
| Handler | `SalesReceiptsMigrationHandler` | `datamigrationio/django_rest/handlers/sales_receipts.py` |
| Validation | `SalesReceiptValidatorService` | `datamigrationio/django_rest/services/sales_receipt_validator.py` |
| Impact preview | `SalesReceiptImpactService` | `datamigrationio/django_rest/services/sales_receipt_impact.py` |
| Import | `SaleReceiptMigrationImporter` + `MigrationSaleReceiptCreateService` | `datamigrationio/django_rest/services/sales_receipt_importer.py` |
| Rollback | `SalesReceiptMigrationRollbackService` | `datamigrationio/django_rest/services/sales_receipt_rollback.py` |
| Async task | `process_sales_receipt_migration` | `datamigrationio/tasks.py` |

Registration:

- Handler is imported in `datamigrationio/django_rest/handlers/__init__.py` **after** `placeholders` so it wins the registry for `sales_receipts`.
- The `sales_receipts` entry was **removed** from `handlers/placeholders.py` so it is no longer a non-importable placeholder.

---

## Handler (`SalesReceiptsMigrationHandler`)

| Attribute | Value |
|-----------|--------|
| `data_type` | `"sales_receipts"` |
| `import_available` | `True` |
| `has_gl_impact` | `True` |
| `is_posting_transaction` | `True` |
| `template_available` | `True` |

**Column aliases** — `COLUMN_ALIAS_MAP` maps human-readable headers (e.g. `"receipt number"`, `"deposit account uid"`) to canonical keys used in validation and import (`receipt_number`, `deposit_account_uid`, …). See the handler file for the full map.

**Required logical fields** (enforced in validation, in addition to customer identity):

- `receipt_number`, `receipt_date`, `line_amount`
- Either a resolvable **product** (name or UID) or an **income account** name (same rule shape as invoices)

**Accounting-oriented mapped fields** (for auto-map hints): deposit account, tax, currency, income account, etc.

**Confirm import** — dispatches `process_sales_receipt_migration` via Celery when `CELERY_BROKER_URL` is set and `DEBUG` is false; otherwise runs `apply()` synchronously (same pattern as invoices).

---

## Validation (`SalesReceiptValidatorService.validate_job`)

For each `DataMigrationRow`:

1. **Mapping** — `FieldMapperService.apply_mapping_to_row` using the handler’s aliases.
2. **Customer** — Resolve by email, then by name variants; company-scoped; not `REMOVED`. Missing / not found → errors.
3. **Receipt number** — Required string.
4. **Receipt date** — Required; parsed with the job’s `date_format`. Invalid → error.
5. **Line amount** — Required decimal ≥ 0; qty × unit price mismatch → warning.
6. **Product** — Optional UID or name; must exist and have income account when product path is used.
7. **Income account** — Optional override by account title; not found → error when provided.
8. **Tax** — Optional `tax_code` / `tax_uid`; not found → warning.
9. **Warehouse** — Optional name or UID; not found → warning.
10. **Term** — Optional; not found → warning.
11. **Deposit account** — Optional name or UID; if provided but not found → **warning** (`DEPOSIT_ACCOUNT_NOT_FOUND`); importer falls back to **Undeposited Funds** when missing.
12. **Duplicates** — If a `Sale` already exists for the customer with `is_sale_receipt=True`, `kind=SALE`, and matching `invoice_id`, `tracking_number`, or `reference_number` to the import receipt number, and the job is configured to skip duplicates → duplicate severity and row `SKIPPED`.

Job moves to **`VALIDATED`** and step **`REVIEW_IMPACT`**; row counters are updated.

---

## Impact preview (`SalesReceiptImpactService.generate`)

- Deletes prior `DataMigrationImpactLine` rows for the job.
- Considers rows in **`READY`** or **`WARNING`** status.
- **Groups** rows by `customer_uid::receipt_number` (same grouping key as import).
- For each line: **income** side as **credit** to the resolved income account; per-line **tax** as **credit** to sales tax payable accounts when tax applies.
- For each receipt group: one **deposit** line — **debit** to the resolved deposit account (or Undeposited Funds for preview when none resolved) for **subtotal + tax** (cash-basis balancing view).

Job moves to **`IMPACT_REVIEWED`** / **`CONFIRM_IMPORT`**.

---

## Import (`SaleReceiptMigrationImporter` + `MigrationSaleReceiptCreateService.create_receipt`)

- Imports **`READY`** rows, and **`WARNING`** rows when `job.allow_warning_import` is true (same as invoices).
- **Groups** by `customer_uid::receipt_number`.
- **Duplicate guard** at import time again (same `Sale` filter as validation); duplicate groups → rows `SKIPPED` with message.
- **Deposit account** — From first row’s `normalized_data.deposit_account_id` if present; otherwise company **Undeposited Funds** chart account. If neither exists, the group **fails** with a clear error.
- **Creates** one `Sale` per group with:
  - `tracking_number` / `invoice_id` from `get_unique_id(..., "SR")` (internal uniqueness)
  - `reference_number` = imported receipt number (external reference)
  - `deposit = total + total_tax`, `due_total = 0`, `status = PAID`
  - `receivable_charter_account` = deposit account (matches WE sale receipt semantics)
- **SaleItem** rows, **FIFO** deduction, **`update_opening_balance`** on COGS / income / asset / tax / deposit — aligned with invoice migration helpers, except **no** customer A/R credit for document total when `due_total` is zero.
- **Journal** — `JournalEntryService.create_journal_entry` with `kind=SALE_RECEPT`, `is_deposit` when deposit account is Undeposited Funds; connectors via `create_journal_entry_connector`.

Job completion status: **`COMPLETED`**, **`PARTIALLY_COMPLETED`**, or **`FAILED`** depending on outcomes; audit events are logged.

---

## Rollback (`SalesReceiptMigrationRollbackService.run`)

Eligible job statuses: completed, partially completed, partially rolled back (same set as invoice rollback).

For each imported row linked to a `Sale` (`linked_record_type = "sale"`):

1. Load all `JournalEntry` rows for that sale and their `JournalEntryConnector` rows.
2. For each connector: **`update_opening_balance`** on the account with the **inverse** debit/credit kind vs the stored connector.
3. Restore **FIFO** `PurchaseItem.quantity` where applicable (same inference as invoice rollback from asset connectors with credit and `purchase_item`).
4. **`_reverse_customer_balance`** — no-op when `due_total` is zero (receipts do not move customer balance for the document total).
5. Delete journal entries, then delete the `Sale` (CASCADE cleans items and connectors tied to the sale).
6. Set migration rows to **`ROLLED_BACK`** and clear link fields; update job **`ROLLED_BACK`** or **`PARTIALLY_ROLLED_BACK`**.

---

## Issue types (`datamigrationio/choices.py`)

Besides shared types (missing field, invalid date/amount, customer not found, etc.), sales receipts use:

| Choice | Meaning |
|--------|---------|
| `DUPLICATE_SALE_RECEIPT` | Same customer + receipt number already exists as a sale receipt. |
| `DEPOSIT_ACCOUNT_NOT_FOUND` | Mapped deposit account missing; import will use Undeposited Funds. |

---

## Template CSV headers

The handler’s `TEMPLATE_HEADERS` (downloadable via the generic template endpoint with `data_type=sales_receipts`) are:

`Customer Name`, `Customer Email`, `Receipt Number`, `Receipt Date`, `Product Name`, `Description`, `Quantity`, `Unit Price`, `Amount`, `Tax Code`, `Deposit Account`, `Payment Method`, `Location`, `Currency`, `Currency Rate`, `Memo`

UID columns (`Product UID`, `Tax UID`, `Deposit Account UID`, `Location UID`) are not in the template but remain supported via column mapping if you upload a custom file that includes them.

*(Payment method is accepted as a mapped column for future use; the current importer does not attach a `PaymentMethod` FK.)*

---

## Related documentation

- [DATA_MIGRATIONS_API.md](DATA_MIGRATIONS_API.md) — REST API and job states.
- [ADDING_NEW_MIGRATION_TYPES.md](../ADDING_NEW_MIGRATION_TYPES.md) — how to add other types; invoices and sales receipts are the posting sale patterns.
