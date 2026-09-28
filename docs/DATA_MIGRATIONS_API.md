# Data Migration API Documentation

All endpoints require `IsAuthenticated`. All operations are scoped to the authenticated user's active company.

**Base URL**: `/api/v1/data-migrations/`

---

## Workflow Overview

A migration job progresses through the following steps in order:

```
select_data_type → upload_file → map_fields → preview_data → validate_data → review_impact → confirm_import → results_audit
```

**Statuses**: `draft` → `uploaded` → `mapped` → `previewed` → `validated` → `impact_reviewed` → `confirmed` → `in_progress` → `completed` / `partially_completed` / `failed` / `cancelled`

---

## 1. Get Supported Data Types

```
GET /api/v1/data-migrations/data-types
```

Returns metadata for all supported migration types.

**Response** `200 OK`
```json
[
  {
    "data_type": "invoices",
    "label": "Invoices",
    "category": "Sales",
    "description": "Import customer invoices for sales.",
    "has_gl_impact": true,
    "is_posting_transaction": true,
    "import_available": true,
    "template_available": true
  }
]
```

**Supported `data_type` values**:

| data_type | Label | Category | GL Impact | Posting | Import Available |
|---|---|---|---|---|---|
| `invoices` | Invoices | Sales | ✓ | ✓ | ✓ |
| `estimates` | Estimates | Sales | ✗ | ✗ | ✓ |
| `sales_receipts` | Sales Receipts | Sales | ✓ | ✓ | ✓ |
| `deposits` | Deposits | Banking | ✓ | ✓ | ✗ |
| `bills` | Bills | Expenses | ✓ | ✓ | ✗ |
| `purchase_orders` | Purchase Orders | Expenses | ✗ | ✗ | ✗ |
| `expenses` | Expenses | Expenses | ✓ | ✓ | ✗ |
| `checks` | Checks | Expenses | ✓ | ✓ | ✗ |
| `journal_entries` | Journal Entries | Accounting | ✓ | ✓ | ✗ |
| `bank_data` | Bank Data | Banking | ✓ | ✗ | ✗ |
| `customers` | Customers | Contacts | ✗ | ✗ | ✗ |
| `vendors` | Vendors | Contacts | ✗ | ✗ | ✗ |
| `products` | Products and Services | Inventory | ✗ | ✗ | ✗ |
| `chart_of_accounts` | Chart of Accounts | Accounting | ✗ | ✗ | ✗ |
| `employees` | Employees | Payroll | ✗ | ✗ | ✗ |
| `locations` | Locations | Settings | ✗ | ✗ | ✗ |
| `opening_balances` | Opening Balances | Accounting | ✓ | ✗ | ✗ |
| `time_activities` | Time Activities | Payroll | ✗ | ✗ | ✗ |
| `open_transactions` | Open Transactions | Accounting | ✓ | ✓ | ✗ |
| `historical_transactions` | Historical Transactions | Accounting | ✓ | ✓ | ✗ |

---

## 2. Create Migration Job

```
POST /api/v1/data-migrations/
```

Creates a new migration job. This is always the first step.

**Request Body**
```json
{
  "data_type": "invoices"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `data_type` | string | ✓ | One of the supported data type values from the table above |

**Response** `201 Created`
```json
{
  "uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "data_type": "invoices",
  "file_name": "",
  "file_type": "",
  "status": "draft",
  "current_step": "upload_file",
  "total_rows": 0,
  "total_columns": 0,
  "ready_rows": 0,
  "warning_rows": 0,
  "error_rows": 0,
  "duplicate_rows": 0,
  "skipped_rows": 0,
  "imported_rows": 0,
  "failed_rows": 0,
  "partially_imported_rows": 0,
  "duplicate_handling": "skip_duplicates",
  "date_format": "MM/DD/YYYY",
  "currency": "USD",
  "decimal_format": "1,234.56",
  "has_header_row": true,
  "confirmed_at": null,
  "completed_at": null,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

---

## 3. List Migration Jobs

```
GET /api/v1/data-migrations/
```

Returns all migration jobs for the authenticated user's active company.

**Response** `200 OK` — array of job objects (same shape as create response)

---

## 4. Get Migration Job Detail

```
GET /api/v1/data-migrations/<uid>/
```

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Response** `200 OK` — same shape as create response

---

## 5. Upload File

```
POST /api/v1/data-migrations/<uid>/upload
```

Upload a CSV/Excel file or pass JSON data directly. Resets any existing rows, mappings, and validation issues on re-upload.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Request** — `multipart/form-data` for file upload, or `application/json` for JSON data

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Conditionally required | CSV or Excel file. Required if `json_data` not provided. |
| `json_data` | array | Conditionally required | Array of row objects. Required if `file` not provided. |
| `date_format` | string | No | Date format used in file. Default: `MM/DD/YYYY`. Options: `MM/DD/YYYY`, `DD/MM/YYYY`, `YYYY-MM-DD`, `YYYY/MM/DD`, `DD-MM-YYYY`, `MM-DD-YYYY` |
| `currency` | string | No | Currency code, max 10 chars. Default: `USD` |
| `decimal_format` | string | No | Decimal format. Default: `1,234.56`. Options: `1,234.56`, `1.234,56` |
| `duplicate_handling` | string | No | Default: `skip_duplicates` |
| `has_header_row` | boolean | No | Whether file has a header row. Default: `true` |

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_rows": 100,
  "total_columns": 27,
  "file_type": "csv",
  "columns": ["Customer Name", "Invoice Number", "Invoice Date", "Due Date", "Amount"]
}
```

**Side effects**: sets `status=uploaded`, `current_step=map_fields`

---

## 6. Preview Data

```
GET /api/v1/data-migrations/<uid>/preview
```

Returns the first N parsed rows from the uploaded file for review.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_rows": 100,
  "total_columns": 27,
  "file_type": "csv",
  "preview_rows": [
    {
      "row_number": 1,
      "raw_data": {
        "Customer Name": "Acme Corp",
        "Invoice Number": "INV-001",
        "Invoice Date": "01/15/2024",
        "Amount": "1500.00"
      }
    }
  ]
}
```

---

## 7. Auto-Map Fields

```
POST /api/v1/data-migrations/<uid>/auto-map
```

Automatically maps source columns to target fields using alias matching. Replaces any existing mappings.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Request Body**: empty `{}`

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "mappings": [
    {
      "uid": "uuid",
      "source_column": "Customer Name",
      "target_field": "customer",
      "is_required": false,
      "affects_accounting": false,
      "status": "mapped"
    }
  ]
}
```

---

## 8. Set Field Mappings Manually

```
POST /api/v1/data-migrations/<uid>/mapping
```

Manually define how source columns map to target fields.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Request Body**
```json
{
  "mappings": [
    {
      "source_column": "Customer Name",
      "target_field": "customer"
    },
    {
      "source_column": "Invoice No",
      "target_field": "invoice_number"
    }
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `mappings` | array | ✓ | Array of source → target mapping objects |
| `mappings[].source_column` | string | ✓ | Column name from uploaded file |
| `mappings[].target_field` | string | ✓ | Target field name in the system |

**Response** `200 OK` — same shape as auto-map response

---

### Invoice Target Fields Reference

| target_field | Description | Required |
|---|---|---|
| `customer` | Customer name | No |
| `invoice_number` | Invoice number / reference | No |
| `invoice_date` | Invoice date | No |
| `due_date` | Payment due date | No |
| `terms` | Payment terms | No |
| `memo` | Memo / notes | No |
| `location` | Location | No |
| `product` | Product or service name | No |
| `description` | Line item description | No |
| `quantity` | Quantity | No |
| `unit_price` | Unit price | No |
| `tax` | Tax code | No |
| `income_account` | Income account | No |
| `amount` | Line amount | No |
| `discount` | Discount | No |
| `warehouse` | Warehouse | No |

---

## 9. Validate Data

```
POST /api/v1/data-migrations/<uid>/validate
```

Runs all business rule validations on every row. For invoices this includes: customer lookup, product lookup, income account lookup, tax lookup, warehouse lookup, term lookup, date format, amount format, duplicate detection, required fields, and closed period checks.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Request Body**: empty `{}`

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_rows": 100,
  "ready_rows": 90,
  "warning_rows": 5,
  "error_rows": 5,
  "ready_percentage": 90.0
}
```

**Side effects**: creates `DataMigrationValidationIssue` records, updates row counters and status on the job

---

## 10. Get Validation Issues

```
GET /api/v1/data-migrations/<uid>/validation-issues
```

Returns all validation issues found during the validate step.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "count": 10,
  "issues": [
    {
      "uid": "uuid",
      "row": "row-uuid",
      "issue_type": "customer_not_found",
      "severity": "error",
      "description": "Customer 'Unknown Corp' not found in system",
      "suggested_fix": "Create a new customer or map to existing one",
      "is_resolved": false,
      "resolved_at": null,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

**`issue_type` values**:

| issue_type | Description | Default Severity |
|---|---|---|
| `customer_not_found` | Customer doesn't exist in system | error |
| `product_not_found` | Product/service doesn't exist | error |
| `product_income_account_missing` | Product has no income account set | warning |
| `income_account_not_found` | Referenced income account not found | error |
| `tax_not_found` | Tax code not found | error |
| `warehouse_not_found` | Warehouse not found | error |
| `term_not_found` | Payment term not found | warning |
| `invalid_date` | Date field has invalid format | error |
| `invalid_amount` | Amount field has invalid format | error |
| `amount_mismatch` | Line amounts don't match total | warning |
| `duplicate_invoice` | Invoice number already exists | duplicate |
| `missing_required_field` | Required field is empty | error |
| `closed_period` | Transaction date falls in closed period | error |

**`severity` values**: `error`, `warning`, `duplicate`

---

## 11. Fix a Row

```
POST /api/v1/data-migrations/<uid>/rows/<row_uid>/fix
```

Applies a correction to a specific row field, re-validates the row, and returns the updated row with its current issues.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |
| `row_uid` | UUID | Row identifier |

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `field` | string | ✓ | The mapped-data field to correct (see table below) |
| `value` | string | ✓ | The corrected value — name/title **or** UID (both accepted for reference fields) |
| `apply_to_similar_records` | boolean | No | Propagate the fix to all rows with the same original mapped value. Default: `false` |

**Accepted `field` values**

| `field` | What `value` should be | Notes |
|---|---|---|
| `customer` or `customer_uid` | Customer name, email, or UID | Resolved by email → name variants → UID |
| `product_service` or `product_uid` | Product title or UID | Case-insensitive title or exact UID |
| `income_account` or `income_account_uid` | Account title or UID | |
| `tax_code` or `tax_uid` | Tax name or UID | |
| `warehouse` or `warehouse_uid` | Warehouse name or UID | |
| `term` or `term_uid` | Term name or UID | |
| `deposit_account` or `deposit_account_uid` | Account title or UID | |
| `invoice_date`, `due_date`, `receipt_date`, `estimate_date`, `expiry_date` | Date string matching the job's `date_format` | |
| `line_amount`, `invoice_number`, `receipt_number`, `estimate_number` | Corrected numeric / string value | |

For all reference fields the service resolves the record in the database (company-scoped), writes the display name into `mapped_data`, the UID/ID into `normalized_data`, then re-runs full row validation and refreshes job counters.

**Example — fix by name**
```json
{
  "field": "customer",
  "value": "Acme Corp",
  "apply_to_similar_records": true
}
```

**Example — fix by UID**
```json
{
  "field": "customer_uid",
  "value": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "apply_to_similar_records": false
}
```

**Response `200 OK`** — fix succeeded and the field issue is resolved

```json
{
  "fixed": true,
  "message": "'customer' was updated and validated successfully.",
  "field": "customer",
  "uid": "row-uuid",
  "row_number": 5,
  "raw_data": { "...": "..." },
  "mapped_data": { "customer": "Acme Corp", "..." : "..." },
  "normalized_data": { "customer_uid": "3fa85f64-...", "customer_id": 42, "..." : "..." },
  "status": "ready",
  "error_count": 0,
  "warning_count": 0,
  "duplicate_count": 0,
  "linked_record_uid": null,
  "linked_record_type": null,
  "message": null,
  "issues": [],
  "similar_rows_fixed": 3
}
```

**Response `400 Bad Request`** — the record was not found, or re-validation still fails for that field after the fix

```json
{
  "fixed": false,
  "message": "Customer 'Acme Corp' does not exist in this company. Please provide an exact name, email, or valid UID.",
  "field": "customer",
  "suggested_fix": "Map this row to an existing customer before import.",
  "uid": "row-uuid",
  "row_number": 5,
  "status": "error",
  "error_count": 1,
  "warning_count": 0,
  "duplicate_count": 0,
  "issues": [
    {
      "uid": "…",
      "issue_type": "customer_not_found",
      "severity": "error",
      "description": "Customer 'Acme Corp' does not exist in this company.",
      "suggested_fix": "Map this row to an existing customer before import.",
      "is_resolved": false,
      "resolved_at": null,
      "created_at": "…"
    }
  ]
}
```

`apply_to_similar_records: true` matches other rows by the row's **original** `mapped_data` value for the field (before the fix). Only rows where the fix also passes re-validation are included in `similar_rows_fixed`.

---

## 12. Review Accounting Impact

```
POST /api/v1/data-migrations/<uid>/review-impact
```

Calculates and returns the GL accounting impact that will result from the import. Must be called before confirm.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Request Body**: empty `{}`

**Response** `200 OK` (invoices example)
```json
{
  "total_transactions": 90,
  "impact_lines": [
    {
      "uid": "uuid",
      "transaction_type": "invoice",
      "account_title": "Accounts Receivable",
      "debit": 15000.00,
      "credit": 0.00,
      "customer_name": "Acme Corp",
      "tax": "Sales Tax",
      "location": "Main Office",
      "report_impact": "Balance Sheet"
    },
    {
      "uid": "uuid",
      "transaction_type": "invoice",
      "account_title": "Sales Revenue",
      "debit": 0.00,
      "credit": 15000.00,
      "customer_name": "Acme Corp",
      "tax": "",
      "location": "Main Office",
      "report_impact": "Income Statement"
    }
  ]
}
```

**Side effects**: creates `DataMigrationImpactLine` records, sets `status=impact_reviewed`

---

## 13. Confirm Import

```
POST /api/v1/data-migrations/<uid>/confirm
```

Confirms and starts the import. Only available when `import_available=true` (currently only `invoices`). Job must have `status=impact_reviewed`.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Request Body**
```json
{
  "understood_financial_impact": true,
  "skip_error_rows": true,
  "send_email": false
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `understood_financial_impact` | boolean | ✓ | Must be `true` — user must acknowledge the GL impact |
| `skip_error_rows` | boolean | No | Must be `true` if the job has `error_rows > 0`. Default: `true` |
| `send_email` | boolean | No | Whether to send email notifications after import. Default: `false` |

**Response** `200 OK` (when import is available)
```json
{
  "implemented": true,
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "confirmed",
  "message": "Import started. Check results endpoint for progress."
}
```

**Response** `200 OK` (when import is not yet implemented for this data_type)
```json
{
  "message": "Import is not implemented yet for this migration type.",
  "data_type": "bills",
  "import_available": false
}
```

**Side effects**: sets `status=confirmed`, `current_step=results_audit`, enqueues async Celery task `process_invoice_migration`

---

## 14. Get Results

```
GET /api/v1/data-migrations/<uid>/results
```

Returns import results. Poll this endpoint after confirming to track async import progress.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "completed",
  "imported": 90,
  "failed": 0,
  "skipped": 10,
  "partially_imported": 0,
  "completed_at": "2024-01-01T12:00:00Z",
  "details": [
    {
      "row_number": 1,
      "invoice_number": "INV-001",
      "status": "imported",
      "message": null,
      "linked_record_uid": "uuid-of-created-invoice"
    },
    {
      "row_number": 2,
      "invoice_number": "INV-002",
      "status": "skipped",
      "message": "Row has unresolved errors",
      "linked_record_uid": null
    }
  ]
}
```

**Row `status` values**: `imported`, `failed`, `skipped`, `partially_imported`

---

## 15. Download Error Report

```
GET /api/v1/data-migrations/<uid>/error-report
```

Downloads a CSV file containing all rows with errors/warnings and their details.

**Response**: CSV file download

---

## 16. Get Audit Logs

```
GET /api/v1/data-migrations/<uid>/audit-logs
```

Returns the audit trail for a migration job (last 100 entries).

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `uid` | UUID | Migration job identifier |

**Response** `200 OK`
```json
{
  "job_uid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "logs": [
    {
      "timestamp": "2024-01-01T10:00:00Z",
      "actor": "user@example.com",
      "action": "created",
      "changes": {}
    },
    {
      "timestamp": "2024-01-01T10:05:00Z",
      "actor": "user@example.com",
      "action": "file_uploaded",
      "changes": {
        "status": ["draft", "uploaded"],
        "total_rows": [0, 100]
      }
    }
  ]
}
```

**Logged `action` values**: `created`, `file_uploaded`, `fields_auto_mapped`, `fields_mapped`, `validation_completed`, `impact_reviewed`, `import_confirmed`

---

## 17. Download Template

```
GET /api/v1/data-migrations/templates/<data_type>/download
```

Downloads a CSV template with the correct column headers for the given data type.

**URL Parameters**

| Param | Type | Description |
|---|---|---|
| `data_type` | string | Any supported data type, e.g. `invoices`, `bills`, `customers` |

**Response**: CSV file download

> Legacy alias: `GET /api/v1/data-migrations/templates/invoices/download`

---

## Error Responses

All endpoints return standard error responses:

**`400 Bad Request`** — validation error
```json
{
  "field_name": ["This field is required."]
}
```

**`401 Unauthorized`** — missing or invalid authentication token

**`403 Forbidden`** — authenticated but not authorized for this company

**`404 Not Found`** — migration job with given UID doesn't exist or belongs to another company

**`500 Internal Server Error`** — unexpected server error

---

## Complete Workflow Example (Invoices)

```bash
# 1. Create job
POST /api/v1/data-migrations/
{ "data_type": "invoices" }
# → uid: "abc-123"

# 2. Upload file
POST /api/v1/data-migrations/abc-123/upload
# multipart with file=invoices.csv

# 3. Auto-map columns
POST /api/v1/data-migrations/abc-123/auto-map

# 4. Review/adjust mappings if needed
POST /api/v1/data-migrations/abc-123/mapping
{ "mappings": [...] }

# 5. Validate
POST /api/v1/data-migrations/abc-123/validate

# 6. Review issues and fix rows
GET /api/v1/data-migrations/abc-123/validation-issues
POST /api/v1/data-migrations/abc-123/rows/<row-uid>/fix
{ "field": "customer_uid", "value": "cust-uid", "apply_to_similar_records": true }

# 7. Review accounting impact
POST /api/v1/data-migrations/abc-123/review-impact

# 8. Confirm import
POST /api/v1/data-migrations/abc-123/confirm
{ "understood_financial_impact": true, "skip_error_rows": true, "send_email": false }

# 9. Poll results
GET /api/v1/data-migrations/abc-123/results
```
