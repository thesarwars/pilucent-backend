Data Migration System Overview
Architecture
The system follows a plug-in handler registry pattern — every data type (invoices, bills, customers, etc.) has its own handler class registered into a central registry. The pipeline logic stays generic; only the handler knows how to validate, preview GL impact, and import for its specific type.


Registry
  └── InvoiceMigrationHandler     ← only fully implemented
  └── EstimatesHandler            ← placeholder (registered, not importable)
  └── BillsHandler                ← placeholder
  └── ... 17 more placeholders
The 8-Step Pipeline
Every migration job progresses through these steps in order:

Step	UI Label	How
1	Select Data Type	POST / → creates job
2	Upload File	POST /<uid>/upload → parses CSV/XLSX/JSON, creates rows
3	Map Fields	POST /<uid>/auto-map or POST /<uid>/mapping
4	Preview Data	GET /<uid>/preview → first N rows preview
5	Validate Data	POST /<uid>/validate → per-row validation, creates issues
6	Review Impact	POST /<uid>/review-impact → GL impact preview lines
7	Confirm Import	POST /<uid>/confirm → triggers Celery async task
8	Results & Audit	GET /<uid>/results, /error-report, /audit-logs
Can You Use It for Any Data Type?
Yes, by design — the handler registry was built exactly for this. Today only invoices is importable; 18 other types are registered as placeholders. To add support for a new type (e.g., bills), you implement:


@MigrationHandlerRegistry.register
class BillsMigrationHandler(BaseMigrationHandler):
    data_type = "bills"
    import_available = True
    # define: get_template_headers, get_field_aliases, validate, review_impact, confirm_import
The views, URL routing, and all 8 steps work without any changes.

Frontend Implementation Guide
State Machine
Track job.current_step and job.status from the detail API response. These drive which screen to show:


current_step         → Screen
─────────────────────────────────
upload_file          → Step 2: File Upload
map_fields           → Step 3: Column Mapping
preview_data         → Step 4: Preview
validate_data        → Step 5: Validation Issues
review_impact        → Step 6: GL Impact Review
confirm_import       → Step 7: Confirm
results_audit        → Step 8: Results
Screen-by-Screen Breakdown
Screen 1 — Select Data Type

GET /data-types
→ Show grid of cards (label, category, description)
→ Gray out cards where import_available = false (show tooltip: "Coming Soon")
→ On select: POST / { data_type: "invoices" } → save job_uid to state
Screen 2 — Upload File

POST /<uid>/upload (multipart/form-data)
  file: <binary>
  date_format: "MM/DD/YYYY"   ← dropdown with 5 options
  currency: "USD"
  has_header_row: true        ← toggle
  duplicate_handling: "skip_duplicates"

Response → show:
  total_rows, total_columns
  columns[]  ← needed for the next mapping step, save to state
Accept .csv, .xlsx, .json
Show detected column count and row count
Button: "Download Template" → GET /templates/invoices/download
Screen 3 — Map Fields
Two sub-modes:

Auto-Map (one click):


POST /<uid>/auto-map → returns mappings[]
Manual Map (table UI):

Left column: source columns from file (from upload response columns[])
Right column: dropdown of target fields (derive from handler's field aliases)
Show required/optional badge per target field
Show "affects accounting" badge

POST /<uid>/mapping { mappings: [{source_column, target_field}, ...] }
Show unmapped required fields as errors before allowing Next.

Screen 4 — Preview Data

GET /<uid>/preview
→ Show first ~10 rows in a table
→ Columns = mapped target fields
→ No state change; "Looks good" button triggers validate
Screen 5 — Validate & Fix Issues

POST /<uid>/validate → { ready_rows, warning_rows, error_rows, duplicate_rows }
GET /<uid>/validation-issues → { issues[] }
Display:

Summary bar: Ready / Warnings / Errors / Duplicates
Filterable issue table: row number, issue type, severity, description, suggested fix
Row Fix: per issue, open a side panel to fix the field value

POST /<uid>/rows/<row_uid>/fix
{ field: "customer_uid", value: "<uuid>", apply_to_similar_records: true }
Re-validate after fixes
Block "Next" if error_rows > 0 (or make it opt-in with a warning)
Issue severity colors: error → red, warning → yellow, duplicate → blue

Screen 6 — Review GL Impact

POST /<uid>/review-impact → { impact_level, total_transactions, total_value, affected_reports[], lines[] }
Display:

Impact badge: "High Impact" (red) / "Medium" (yellow) / "Low" (green)
Summary: total transactions + total value
Affected reports list: Balance Sheet, Profit & Loss, etc.
Impact lines table:
Account	Type	Debit	Credit	Customer	Report
Accounts Receivable	accounts_receivable	5000	—	Acme	Balance Sheet
Services Income	income	—	4500	Acme	Profit & Loss
Sales Tax Payable	tax_payable	—	500	Acme	Sales Tax Report
User must acknowledge before proceeding.

Screen 7 — Confirm Import

POST /<uid>/confirm
{
  understood_financial_impact: true,   ← required checkbox
  skip_error_rows: true,               ← optional toggle
  send_email: false                    ← optional toggle
}
Show a summary card: total rows, breakdown, what will be skipped. Large prominent "Confirm Import" button.

After confirm → job enters async processing. Poll GET /<uid> every 3–5 seconds watching status:


confirmed → in_progress → completed / partially_completed / failed
Show a progress spinner with counters updating.

Screen 8 — Results & Audit

GET /<uid>/results → { status, imported, failed, skipped, details[] }
GET /<uid>/audit-logs
GET /<uid>/error-report  ← triggers CSV download
Display:

Summary: imported / failed / skipped counts
Row results table: row number, invoice number, status (green/red/gray), linked record UID (clickable link to invoice)
"Download Error Report" button for failed rows
Audit log timeline
API Flow Diagram

[Select Type] ──POST /──────────────────────── job created
[Upload File] ──POST /<uid>/upload ─────────── rows created
[Auto-Map]    ──POST /<uid>/auto-map ────────── mappings saved
                ──OR──
[Manual Map]  ──POST /<uid>/mapping ────────── mappings saved
[Preview]     ──GET  /<uid>/preview ────────── read-only
[Validate]    ──POST /<uid>/validate ────────── issues created
[Fix Issues]  ──POST /<uid>/rows/<row>/fix ─── loop until resolved
[Impact]      ──POST /<uid>/review-impact ───── impact lines created
[Confirm]     ──POST /<uid>/confirm ─────────── Celery task queued
[Poll]        ──GET  /<uid> (polling) ────────── watch status
[Results]     ──GET  /<uid>/results ─────────── final outcome
Key Frontend Data to Track in State

{
  jobUid: string,
  dataType: string,
  currentStep: string,       // drives screen routing
  status: string,            // drives loading/completed states
  uploadedColumns: string[], // needed for manual mapping screen
  counters: {
    totalRows, readyRows, warningRows, errorRows, duplicateRows, importedRows, failedRows
  }
}
The job.current_step field tells you exactly where to resume if the user navigates away and comes back — it is your progress tracker.