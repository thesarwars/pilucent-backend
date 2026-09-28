# Data Migration — Next.js Frontend Implementation Guide

Complete step-by-step guide for building the data migration wizard UI in Next.js.

---

## Table of Contents

1. [Overview & Flow](#1-overview--flow)
2. [Base API Setup](#2-base-api-setup)
3. [TypeScript Types](#3-typescript-types)
4. [API Client Functions](#4-api-client-functions)
5. [Step 1 — Select Data Type](#5-step-1--select-data-type)
6. [Step 2 — Upload File](#6-step-2--upload-file)
7. [Step 3 — Map Fields](#7-step-3--map-fields)
8. [Step 4 — Preview Data](#8-step-4--preview-data)
9. [Step 5 — Validate Data](#9-step-5--validate-data)
10. [Step 6 — Review Impact](#10-step-6--review-impact)
11. [Step 7 — Confirm Import](#11-step-7--confirm-import)
12. [Step 8 — Results & Audit](#12-step-8--results--audit)
13. [Wizard State Management](#13-wizard-state-management)
14. [Wizard Shell Component](#14-wizard-shell-component)
15. [Error Handling Patterns](#15-error-handling-patterns)
16. [Template Download & Utilities](#16-template-download--utilities)

---

## 1. Overview & Flow

The migration wizard has **8 sequential steps**. Each step calls a specific API endpoint and advances the `current_step` and `status` fields on the backend job object.

```
select_data_type → upload_file → map_fields → preview_data
    → validate_data → review_impact → confirm_import → results_audit
```

**Backend status progression:**
```
draft → uploaded → mapped → previewed → validated → impact_reviewed → confirmed → in_progress → completed / partially_completed / failed
```

**Base API URL:** `/api/v1/we/data-migrations`

All requests must include an `Authorization: Bearer <token>` header (or use your existing auth cookie/session setup).

---

## 2. Base API Setup

### `lib/api/client.ts`

```ts
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAuthToken(); // replace with your actual token getter

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ message: res.statusText }));
    throw new ApiError(res.status, error.message ?? "Request failed", error);
  }

  // Some endpoints return no body (204) or a file
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return res.json() as Promise<T>;
  }
  return res as unknown as T;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}
```

---

## 3. TypeScript Types

### `lib/types/datamigration.ts`

```ts
// ─── Enums ───────────────────────────────────────────────────────────────────

export type MigrationStatus =
  | "draft"
  | "uploaded"
  | "mapped"
  | "previewed"
  | "validated"
  | "impact_reviewed"
  | "confirmed"
  | "in_progress"
  | "completed"
  | "partially_completed"
  | "failed"
  | "cancelled";

export type MigrationStep =
  | "select_data_type"
  | "upload_file"
  | "map_fields"
  | "preview_data"
  | "validate_data"
  | "review_impact"
  | "confirm_import"
  | "results_audit";

export type RowStatus =
  | "pending"
  | "ready"
  | "warning"
  | "error"
  | "duplicate"
  | "skipped"
  | "imported"
  | "failed";

export type IssueSeverity = "error" | "warning" | "duplicate";

export type IssueType =
  | "customer_not_found"
  | "product_not_found"
  | "product_income_account_missing"
  | "income_account_not_found"
  | "tax_not_found"
  | "warehouse_not_found"
  | "term_not_found"
  | "invalid_date"
  | "invalid_amount"
  | "amount_mismatch"
  | "duplicate_invoice"
  | "missing_required_field"
  | "closed_period";

export type DataType =
  | "invoices"
  | "estimates"
  | "sales_receipts"
  | "deposits"
  | "bills"
  | "purchase_orders"
  | "expenses"
  | "checks"
  | "journal_entries"
  | "bank_data"
  | "customers"
  | "vendors"
  | "products"
  | "chart_of_accounts"
  | "employees"
  | "locations"
  | "opening_balances"
  | "time_activities"
  | "open_transactions"
  | "historical_transactions";

// ─── API Response Types ───────────────────────────────────────────────────────

export interface DataTypeOption {
  data_type: DataType;
  label: string;
  category: string;
  description: string;
  has_gl_impact: boolean;
  is_posting_transaction: boolean;
  import_available: boolean;
  template_available: boolean;
}

export interface MigrationJobList {
  uid: string;
  data_type: DataType;
  file_name: string;
  file_type: string;
  status: MigrationStatus;
  current_step: MigrationStep;
  total_rows: number;
  ready_rows: number;
  warning_rows: number;
  error_rows: number;
  duplicate_rows: number;
  skipped_rows: number;
  imported_rows: number;
  failed_rows: number;
  created_at: string;
  updated_at: string;
}

export interface MigrationJobDetail extends MigrationJobList {
  total_columns: number;
  partially_imported_rows: number;
  duplicate_handling: string;
  date_format: string;
  currency: string;
  decimal_format: string;
  has_header_row: boolean;
  confirmed_at: string | null;
  completed_at: string | null;
}

export interface UploadResponse {
  job_uid: string;
  total_rows: number;
  total_columns: number;
  file_type: string;
  columns: string[];
}

export interface PreviewRow {
  row_number: number;
  raw_data: Record<string, string>;
}

export interface PreviewResponse {
  job_uid: string;
  total_rows: number;
  total_columns: number;
  file_type: string;
  preview_rows: PreviewRow[];
}

export interface FieldMapping {
  uid: string;
  source_column: string;
  target_field: string;
  is_required: boolean;
  affects_accounting: boolean;
  status: string;
}

export interface AutoMapResponse {
  job_uid: string;
  mappings: FieldMapping[];
}

export interface ValidationIssue {
  uid: string;
  row: string; // row uid
  issue_type: IssueType;
  severity: IssueSeverity;
  description: string;
  suggested_fix: string | null;
  is_resolved: boolean;
  resolved_at: string | null;
  created_at: string;
}

export interface ValidationIssuesResponse {
  job_uid: string;
  count: number;
  issues: ValidationIssue[];
}

export interface ImpactLine {
  uid: string;
  transaction_type: string;
  account_title: string | null;
  debit: number;
  credit: number;
  customer_name: string | null;
  tax: string | null;
  location: string | null;
  report_impact: string | null;
}

export interface ImpactResponse {
  total_transactions: number;
  total_debit: number;
  total_credit: number;
  impact_lines: ImpactLine[];
}

export interface ConfirmResponse {
  status: MigrationStatus;
  imported_rows: number;
  failed_rows: number;
  skipped_rows: number;
  partially_imported_rows: number;
  message: string;
}

export interface ResultDetail {
  row_number: number;
  invoice_number?: string;
  status: RowStatus;
  message: string | null;
  linked_record_uid: string | null;
}

export interface ResultsResponse {
  job_uid: string;
  status: MigrationStatus;
  imported: number;
  failed: number;
  skipped: number;
  partially_imported: number;
  completed_at: string;
  details: ResultDetail[];
}

export interface AuditLog {
  timestamp: string;
  actor: string;
  action: string;
  changes: Record<string, [unknown, unknown]>;
}

export interface AuditLogsResponse {
  job_uid: string;
  logs: AuditLog[];
}

// ─── Request Types ────────────────────────────────────────────────────────────

export interface CreateMigrationPayload {
  data_type: DataType;
}

export interface UploadPayload {
  file?: File;
  json_data?: Record<string, unknown>[];
  date_format?: string;
  currency?: string;
  decimal_format?: string;
  duplicate_handling?: string;
  has_header_row?: boolean;
}

export interface MappingEntry {
  source_column: string;
  target_field: string;
}

export interface SaveMappingPayload {
  mappings: MappingEntry[];
}

export interface RowFixPayload {
  field: string;
  value: unknown;
  apply_to_similar_records?: boolean;
}

export interface ConfirmPayload {
  understood_financial_impact: boolean;
  skip_error_rows?: boolean;
  send_email?: boolean;
}
```

---

## 4. API Client Functions

### `lib/api/datamigration.ts`

```ts
import { apiFetch } from "./client";
import type {
  MigrationJobList,
  MigrationJobDetail,
  DataTypeOption,
  UploadResponse,
  UploadPayload,
  PreviewResponse,
  AutoMapResponse,
  SaveMappingPayload,
  FieldMapping,
  ValidationIssuesResponse,
  RowFixPayload,
  ImpactResponse,
  ConfirmPayload,
  ConfirmResponse,
  ResultsResponse,
  AuditLogsResponse,
  CreateMigrationPayload,
} from "../types/datamigration";

const BASE = "/api/v1/we/data-migrations";

// List all migrations for the active company
export function listMigrations(): Promise<MigrationJobList[]> {
  return apiFetch(`${BASE}`);
}

// Create a new migration job (returns detail)
export function createMigration(
  payload: CreateMigrationPayload
): Promise<MigrationJobDetail> {
  return apiFetch(`${BASE}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// Get migration detail
export function getMigration(uid: string): Promise<MigrationJobDetail> {
  return apiFetch(`${BASE}/${uid}`);
}

// Get available data types
export function getDataTypes(): Promise<DataTypeOption[]> {
  return apiFetch(`${BASE}/data-types`);
}

// Upload or re-upload a file
export function uploadFile(
  uid: string,
  payload: UploadPayload
): Promise<UploadResponse> {
  const form = new FormData();
  if (payload.file) form.append("file", payload.file);
  if (payload.json_data)
    form.append("json_data", JSON.stringify(payload.json_data));
  if (payload.date_format) form.append("date_format", payload.date_format);
  if (payload.currency) form.append("currency", payload.currency);
  if (payload.decimal_format)
    form.append("decimal_format", payload.decimal_format);
  if (payload.duplicate_handling)
    form.append("duplicate_handling", payload.duplicate_handling);
  if (payload.has_header_row !== undefined)
    form.append("has_header_row", String(payload.has_header_row));

  return apiFetch(`${BASE}/${uid}/upload`, { method: "POST", body: form });
}

// Get a preview of parsed rows (first ~10 rows)
export function previewMigration(uid: string): Promise<PreviewResponse> {
  return apiFetch(`${BASE}/${uid}/preview`);
}

// Auto-map columns to system fields
export function autoMap(uid: string): Promise<AutoMapResponse> {
  return apiFetch(`${BASE}/${uid}/auto-map`, { method: "POST" });
}

// Save custom field mappings
export function saveMappings(
  uid: string,
  payload: SaveMappingPayload
): Promise<{ job_uid: string; mappings: FieldMapping[] }> {
  return apiFetch(`${BASE}/${uid}/mapping`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// Run validation
export function validateMigration(uid: string): Promise<unknown> {
  return apiFetch(`${BASE}/${uid}/validate`, { method: "POST" });
}

// Get validation issues
export function getValidationIssues(
  uid: string
): Promise<ValidationIssuesResponse> {
  return apiFetch(`${BASE}/${uid}/validation-issues`);
}

// Fix a specific row
export function fixRow(
  uid: string,
  rowUid: string,
  payload: RowFixPayload
): Promise<unknown> {
  return apiFetch(`${BASE}/${uid}/rows/${rowUid}/fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// Generate financial impact report
export function reviewImpact(uid: string): Promise<ImpactResponse> {
  return apiFetch(`${BASE}/${uid}/review-impact`, { method: "POST" });
}

// Confirm and start import
export function confirmImport(
  uid: string,
  payload: ConfirmPayload
): Promise<ConfirmResponse> {
  return apiFetch(`${BASE}/${uid}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// Get import results
export function getResults(uid: string): Promise<ResultsResponse> {
  return apiFetch(`${BASE}/${uid}/results`);
}

// Download error report (returns a Blob)
export async function downloadErrorReport(uid: string): Promise<Blob> {
  const res = await apiFetch<Response>(`${BASE}/${uid}/error-report`);
  return (res as unknown as Response).blob();
}

// Get audit logs
export function getAuditLogs(uid: string): Promise<AuditLogsResponse> {
  return apiFetch(`${BASE}/${uid}/audit-logs`);
}

// Download a CSV template for a data type
export async function downloadTemplate(dataType: string): Promise<Blob> {
  const res = await apiFetch<Response>(
    `${BASE}/templates/${dataType}/download`
  );
  return (res as unknown as Response).blob();
}
```

---

## 5. Step 1 — Select Data Type

**What it does:** Fetches available data types and lets the user pick one.  
**API call:** `GET /data-types` → then `POST /` to create the job.

```tsx
// components/datamigration/steps/SelectDataType.tsx
"use client";

import { useEffect, useState } from "react";
import { getDataTypes, createMigration } from "@/lib/api/datamigration";
import type { DataTypeOption, DataType } from "@/lib/types/datamigration";

interface Props {
  onCreated: (uid: string) => void;
}

const CATEGORY_ORDER = ["transactions", "contacts", "products", "accounts", "payroll", "other"];

export function SelectDataType({ onCreated }: Props) {
  const [types, setTypes] = useState<DataTypeOption[]>([]);
  const [selected, setSelected] = useState<DataType | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDataTypes().then(setTypes).catch(() => setError("Failed to load data types."));
  }, []);

  const grouped = types.reduce<Record<string, DataTypeOption[]>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});

  async function handleNext() {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const job = await createMigration({ data_type: selected });
      onCreated(job.uid);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create migration.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2>Select Data Type</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}

      {CATEGORY_ORDER.map((cat) =>
        grouped[cat] ? (
          <div key={cat}>
            <h3 style={{ textTransform: "capitalize" }}>{cat}</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
              {grouped[cat].map((t) => (
                <button
                  key={t.data_type}
                  onClick={() => setSelected(t.data_type)}
                  disabled={!t.import_available}
                  style={{
                    border: selected === t.data_type ? "2px solid blue" : "1px solid #ccc",
                    padding: 12,
                    borderRadius: 6,
                    background: !t.import_available ? "#f5f5f5" : "white",
                    cursor: t.import_available ? "pointer" : "not-allowed",
                    opacity: t.import_available ? 1 : 0.5,
                  }}
                >
                  <strong>{t.label}</strong>
                  {!t.import_available && <span> (Coming soon)</span>}
                </button>
              ))}
            </div>
          </div>
        ) : null
      )}

      <button onClick={handleNext} disabled={!selected || loading}>
        {loading ? "Creating..." : "Next"}
      </button>
    </div>
  );
}
```

---

## 6. Step 2 — Upload File

**What it does:** Accepts CSV / XLSX / JSON and optional settings.  
**API calls:** `POST /{uid}/upload`

```tsx
// components/datamigration/steps/UploadFile.tsx
"use client";

import { useRef, useState } from "react";
import { uploadFile, downloadTemplate } from "@/lib/api/datamigration";
import type { UploadPayload, DataType } from "@/lib/types/datamigration";

interface Props {
  uid: string;
  dataType: DataType;
  onUploaded: (columns: string[]) => void;
}

export function UploadFile({ uid, dataType, onUploaded }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [settings, setSettings] = useState<Partial<UploadPayload>>({
    date_format: "MM/DD/YYYY",
    currency: "USD",
    decimal_format: "1,234.56",
    duplicate_handling: "skip_duplicates",
    has_header_row: true,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Please select a file.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await uploadFile(uid, { file, ...settings });
      onUploaded(res.columns);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleTemplateDownload() {
    try {
      const blob = await downloadTemplate(dataType);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${dataType}_template.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Template not available for this data type.");
    }
  }

  return (
    <div>
      <h2>Upload File</h2>

      <button type="button" onClick={handleTemplateDownload}>
        Download Template CSV
      </button>

      <div>
        <label>File (CSV, XLSX, JSON)</label>
        <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.json" />
      </div>

      <div>
        <label>Date Format</label>
        <select
          value={settings.date_format}
          onChange={(e) => setSettings((s) => ({ ...s, date_format: e.target.value }))}
        >
          <option value="MM/DD/YYYY">MM/DD/YYYY</option>
          <option value="DD/MM/YYYY">DD/MM/YYYY</option>
          <option value="YYYY-MM-DD">YYYY-MM-DD</option>
        </select>
      </div>

      <div>
        <label>Currency</label>
        <input
          value={settings.currency}
          onChange={(e) => setSettings((s) => ({ ...s, currency: e.target.value }))}
        />
      </div>

      <div>
        <label>Decimal Format</label>
        <select
          value={settings.decimal_format}
          onChange={(e) => setSettings((s) => ({ ...s, decimal_format: e.target.value }))}
        >
          <option value="1,234.56">1,234.56 (US)</option>
          <option value="1.234,56">1.234,56 (EU)</option>
        </select>
      </div>

      <div>
        <label>
          <input
            type="checkbox"
            checked={settings.has_header_row}
            onChange={(e) => setSettings((s) => ({ ...s, has_header_row: e.target.checked }))}
          />
          First row is a header
        </label>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <button onClick={handleUpload} disabled={loading}>
        {loading ? "Uploading..." : "Upload & Continue"}
      </button>
    </div>
  );
}
```

---

## 7. Step 3 — Map Fields

**What it does:** Auto-maps columns to system fields. User can correct mappings.  
**API calls:** `POST /{uid}/auto-map` → user edits → `POST /{uid}/mapping`

```tsx
// components/datamigration/steps/MapFields.tsx
"use client";

import { useEffect, useState } from "react";
import { autoMap, saveMappings } from "@/lib/api/datamigration";
import type { FieldMapping, MappingEntry } from "@/lib/types/datamigration";

// Replace with real system target fields for your data type
const INVOICE_TARGET_FIELDS = [
  { value: "", label: "— Ignore this column —" },
  { value: "invoice_number", label: "Invoice Number" },
  { value: "customer_uid", label: "Customer" },
  { value: "invoice_date", label: "Invoice Date" },
  { value: "due_date", label: "Due Date" },
  { value: "product_uid", label: "Product / Service" },
  { value: "quantity", label: "Quantity" },
  { value: "unit_price", label: "Unit Price" },
  { value: "tax_uid", label: "Tax" },
  { value: "memo", label: "Memo" },
  { value: "location_uid", label: "Location" },
];

interface Props {
  uid: string;
  onMapped: () => void;
}

export function MapFields({ uid, onMapped }: Props) {
  const [mappings, setMappings] = useState<FieldMapping[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    autoMap(uid)
      .then((res) => setMappings(res.mappings))
      .catch(() => setError("Auto-mapping failed."))
      .finally(() => setLoading(false));
  }, [uid]);

  function updateMapping(index: number, targetField: string) {
    setMappings((prev) =>
      prev.map((m, i) => (i === index ? { ...m, target_field: targetField } : m))
    );
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    const payload: MappingEntry[] = mappings
      .filter((m) => m.target_field)
      .map((m) => ({ source_column: m.source_column, target_field: m.target_field }));
    try {
      await saveMappings(uid, { mappings: payload });
      onMapped();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save mappings.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p>Loading column suggestions...</p>;

  return (
    <div>
      <h2>Map Fields</h2>
      <p>Match your file columns to system fields. Required fields are marked *.</p>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: 8 }}>Your Column</th>
            <th style={{ textAlign: "left", padding: 8 }}>Maps To</th>
            <th style={{ textAlign: "left", padding: 8 }}>Required</th>
          </tr>
        </thead>
        <tbody>
          {mappings.map((m, i) => (
            <tr key={m.uid} style={{ borderBottom: "1px solid #eee" }}>
              <td style={{ padding: 8 }}>{m.source_column}</td>
              <td style={{ padding: 8 }}>
                <select
                  value={m.target_field}
                  onChange={(e) => updateMapping(i, e.target.value)}
                >
                  {INVOICE_TARGET_FIELDS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </td>
              <td style={{ padding: 8 }}>
                {m.is_required ? <span style={{ color: "red" }}>*</span> : null}
                {m.affects_accounting && (
                  <span title="Affects accounting" style={{ marginLeft: 4 }}>⚠</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button onClick={handleSave} disabled={saving}>
        {saving ? "Saving..." : "Save Mappings & Continue"}
      </button>
    </div>
  );
}
```

---

## 8. Step 4 — Preview Data

**What it does:** Shows parsed rows so the user can verify before validation.  
**API calls:** `GET /{uid}/preview`

```tsx
// components/datamigration/steps/PreviewData.tsx
"use client";

import { useEffect, useState } from "react";
import { previewMigration } from "@/lib/api/datamigration";
import type { PreviewRow } from "@/lib/types/datamigration";

interface Props {
  uid: string;
  onConfirmed: () => void;
}

export function PreviewData({ uid, onConfirmed }: Props) {
  const [rows, setRows] = useState<PreviewRow[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    previewMigration(uid)
      .then((res) => {
        setRows(res.preview_rows);
        setTotalRows(res.total_rows);
        if (res.preview_rows.length > 0) {
          setColumns(Object.keys(res.preview_rows[0].raw_data));
        }
      })
      .finally(() => setLoading(false));
  }, [uid]);

  if (loading) return <p>Loading preview...</p>;

  return (
    <div>
      <h2>Preview Data</h2>
      <p>
        Showing {rows.length} of {totalRows} rows. Verify the data looks correct.
      </p>

      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", minWidth: "100%" }}>
          <thead>
            <tr>
              <th style={{ padding: "6px 12px", border: "1px solid #ddd" }}>#</th>
              {columns.map((col) => (
                <th key={col} style={{ padding: "6px 12px", border: "1px solid #ddd" }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.row_number}>
                <td style={{ padding: "6px 12px", border: "1px solid #ddd" }}>
                  {row.row_number}
                </td>
                {columns.map((col) => (
                  <td key={col} style={{ padding: "6px 12px", border: "1px solid #ddd" }}>
                    {row.raw_data[col] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button onClick={onConfirmed}>Looks Good — Validate</button>
    </div>
  );
}
```

---

## 9. Step 5 — Validate Data

**What it does:** Triggers validation on the backend, then shows issues grouped by severity. Allows inline fixing.  
**API calls:** `POST /{uid}/validate` → `GET /{uid}/validation-issues` → `POST /{uid}/rows/{row_uid}/fix`

```tsx
// components/datamigration/steps/ValidateData.tsx
"use client";

import { useEffect, useState } from "react";
import {
  validateMigration,
  getValidationIssues,
  fixRow,
} from "@/lib/api/datamigration";
import type { ValidationIssue } from "@/lib/types/datamigration";

interface Props {
  uid: string;
  onValidated: () => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  error: "#fee2e2",
  warning: "#fef9c3",
  duplicate: "#e0e7ff",
};

export function ValidateData({ uid, onValidated }: Props) {
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [count, setCount] = useState(0);
  const [validating, setValidating] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function runValidation() {
    setValidating(true);
    setError(null);
    try {
      await validateMigration(uid);
      const res = await getValidationIssues(uid);
      setIssues(res.issues);
      setCount(res.count);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Validation failed.");
    } finally {
      setValidating(false);
    }
  }

  useEffect(() => {
    runValidation();
  }, [uid]);

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.filter((i) => i.severity === "warning").length;

  return (
    <div>
      <h2>Validate Data</h2>

      {validating && <p>Running validation...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      {!validating && (
        <>
          <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
            <span style={{ color: "red" }}>Errors: {errorCount}</span>
            <span style={{ color: "#ca8a04" }}>Warnings: {warningCount}</span>
            <span>Total Issues: {count}</span>
          </div>

          {count === 0 && (
            <p style={{ color: "green" }}>All rows are valid. Ready to proceed.</p>
          )}

          {issues.map((issue) => (
            <IssueCard key={issue.uid} issue={issue} jobUid={uid} onFixed={runValidation} />
          ))}

          <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
            <button onClick={onValidated} disabled={errorCount > 0}>
              Continue (errors must be fixed)
            </button>
            {errorCount > 0 && (
              <button onClick={onValidated}>
                Continue Anyway (skip error rows on import)
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function IssueCard({
  issue,
  jobUid,
  onFixed,
}: {
  issue: ValidationIssue;
  jobUid: string;
  onFixed: () => void;
}) {
  const [fixValue, setFixValue] = useState("");
  const [fixing, setFixing] = useState(false);

  async function applyFix() {
    if (!fixValue) return;
    setFixing(true);
    try {
      await fixRow(jobUid, issue.row, {
        field: issue.issue_type,
        value: fixValue,
        apply_to_similar_records: false,
      });
      onFixed();
    } catch {
      alert("Failed to apply fix.");
    } finally {
      setFixing(false);
    }
  }

  return (
    <div
      style={{
        background: SEVERITY_COLOR[issue.severity],
        border: "1px solid #ccc",
        borderRadius: 6,
        padding: 12,
        marginBottom: 8,
      }}
    >
      <div style={{ fontWeight: 600 }}>{issue.description}</div>
      {issue.suggested_fix && (
        <div style={{ fontSize: 13, color: "#555", marginTop: 4 }}>
          Suggested: {issue.suggested_fix}
        </div>
      )}
      {!issue.is_resolved && (
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <input
            placeholder="Enter fix value..."
            value={fixValue}
            onChange={(e) => setFixValue(e.target.value)}
            style={{ flex: 1 }}
          />
          <button onClick={applyFix} disabled={fixing}>
            {fixing ? "Fixing..." : "Apply Fix"}
          </button>
        </div>
      )}
      {issue.is_resolved && (
        <div style={{ color: "green", marginTop: 4 }}>✓ Resolved</div>
      )}
    </div>
  );
}
```

---

## 10. Step 6 — Review Impact

**What it does:** Generates and displays the accounting journal impact (debits/credits per account).  
**API calls:** `POST /{uid}/review-impact`

```tsx
// components/datamigration/steps/ReviewImpact.tsx
"use client";

import { useEffect, useState } from "react";
import { reviewImpact } from "@/lib/api/datamigration";
import type { ImpactResponse, ImpactLine } from "@/lib/types/datamigration";

interface Props {
  uid: string;
  onReviewed: () => void;
}

function formatMoney(n: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(n);
}

export function ReviewImpact({ uid, onReviewed }: Props) {
  const [impact, setImpact] = useState<ImpactResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    reviewImpact(uid)
      .then(setImpact)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Failed to generate impact.")
      )
      .finally(() => setLoading(false));
  }, [uid]);

  if (loading) return <p>Generating financial impact...</p>;
  if (error) return <p style={{ color: "red" }}>{error}</p>;
  if (!impact) return null;

  // Group impact lines by report_impact (Balance Sheet / Income Statement)
  const grouped = impact.impact_lines.reduce<Record<string, ImpactLine[]>>(
    (acc, line) => {
      const key = line.report_impact ?? "Other";
      (acc[key] ??= []).push(line);
      return acc;
    },
    {}
  );

  return (
    <div>
      <h2>Review Financial Impact</h2>
      <p>
        {impact.total_transactions} transactions — Total Debit:{" "}
        {formatMoney(impact.total_debit)} | Total Credit:{" "}
        {formatMoney(impact.total_credit)}
      </p>

      {Object.entries(grouped).map(([section, lines]) => (
        <div key={section} style={{ marginBottom: 24 }}>
          <h3>{section}</h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f3f4f6" }}>
                <th style={{ padding: "8px", textAlign: "left" }}>Account</th>
                <th style={{ padding: "8px", textAlign: "left" }}>Customer</th>
                <th style={{ padding: "8px", textAlign: "right" }}>Debit</th>
                <th style={{ padding: "8px", textAlign: "right" }}>Credit</th>
                <th style={{ padding: "8px", textAlign: "left" }}>Location</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.uid} style={{ borderBottom: "1px solid #e5e7eb" }}>
                  <td style={{ padding: "8px" }}>{line.account_title ?? "—"}</td>
                  <td style={{ padding: "8px" }}>{line.customer_name ?? "—"}</td>
                  <td style={{ padding: "8px", textAlign: "right" }}>
                    {line.debit > 0 ? formatMoney(line.debit) : "—"}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right" }}>
                    {line.credit > 0 ? formatMoney(line.credit) : "—"}
                  </td>
                  <td style={{ padding: "8px" }}>{line.location ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <div
        style={{
          background: "#fef3c7",
          border: "1px solid #f59e0b",
          borderRadius: 6,
          padding: 12,
          marginBottom: 16,
        }}
      >
        ⚠ These entries will be posted to your books upon confirmation. This cannot be undone.
      </div>

      <button onClick={onReviewed}>I Understand — Proceed to Confirm</button>
    </div>
  );
}
```

---

## 11. Step 7 — Confirm Import

**What it does:** Final confirmation before importing. Handles error rows and in-progress polling.  
**API calls:** `POST /{uid}/confirm`

```tsx
// components/datamigration/steps/ConfirmImport.tsx
"use client";

import { useState } from "react";
import { confirmImport, getMigration } from "@/lib/api/datamigration";
import type { MigrationJobDetail } from "@/lib/types/datamigration";

interface Props {
  uid: string;
  job: MigrationJobDetail;
  onImported: () => void;
}

export function ConfirmImport({ uid, job, onImported }: Props) {
  const [skipErrors, setSkipErrors] = useState(false);
  const [sendEmail, setSendEmail] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setConfirming(true);
    setError(null);
    try {
      const res = await confirmImport(uid, {
        understood_financial_impact: true,
        skip_error_rows: skipErrors,
        send_email: sendEmail,
      });

      // If the import runs asynchronously (in_progress), poll for completion
      if (res.status === "in_progress") {
        await pollUntilDone(uid);
      }

      onImported();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Confirmation failed.");
    } finally {
      setConfirming(false);
    }
  }

  async function pollUntilDone(uid: string) {
    const INTERVAL = 3000;
    const MAX_WAIT = 5 * 60 * 1000; // 5 minutes
    const start = Date.now();

    while (Date.now() - start < MAX_WAIT) {
      await new Promise((r) => setTimeout(r, INTERVAL));
      const job = await getMigration(uid);
      if (["completed", "partially_completed", "failed"].includes(job.status)) {
        return;
      }
    }
    throw new Error("Import timed out. Check results page for status.");
  }

  return (
    <div>
      <h2>Confirm Import</h2>

      <div style={{ marginBottom: 16 }}>
        <strong>Summary</strong>
        <ul>
          <li>Total rows: {job.total_rows}</li>
          <li style={{ color: "green" }}>Ready: {job.ready_rows}</li>
          <li style={{ color: "#ca8a04" }}>Warnings: {job.warning_rows}</li>
          <li style={{ color: "red" }}>Errors: {job.error_rows}</li>
          <li>Duplicates: {job.duplicate_rows}</li>
        </ul>
      </div>

      {job.error_rows > 0 && (
        <div style={{ marginBottom: 12 }}>
          <label>
            <input
              type="checkbox"
              checked={skipErrors}
              onChange={(e) => setSkipErrors(e.target.checked)}
            />
            {" "}Skip {job.error_rows} error rows and import the rest
          </label>
        </div>
      )}

      <div style={{ marginBottom: 12 }}>
        <label>
          <input
            type="checkbox"
            checked={sendEmail}
            onChange={(e) => setSendEmail(e.target.checked)}
          />
          {" "}Email me when import is complete
        </label>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {confirming && (
        <p>
          Importing... This may take a moment.
        </p>
      )}

      <button
        onClick={handleConfirm}
        disabled={confirming || (job.error_rows > 0 && !skipErrors)}
      >
        {confirming ? "Importing..." : "Start Import"}
      </button>
    </div>
  );
}
```

---

## 12. Step 8 — Results & Audit

**What it does:** Shows import results per row and allows error report download.  
**API calls:** `GET /{uid}/results` + `GET /{uid}/audit-logs` + `GET /{uid}/error-report`

```tsx
// components/datamigration/steps/ResultsAudit.tsx
"use client";

import { useEffect, useState } from "react";
import {
  getResults,
  getAuditLogs,
  downloadErrorReport,
} from "@/lib/api/datamigration";
import type { ResultsResponse, AuditLogsResponse, RowStatus } from "@/lib/types/datamigration";

interface Props {
  uid: string;
}

const STATUS_COLOR: Record<RowStatus, string> = {
  imported: "green",
  failed: "red",
  skipped: "gray",
  pending: "gray",
  ready: "green",
  warning: "#ca8a04",
  error: "red",
  duplicate: "#6366f1",
  partially_imported: "#f97316",
} as Record<RowStatus, string>;

export function ResultsAudit({ uid }: Props) {
  const [results, setResults] = useState<ResultsResponse | null>(null);
  const [logs, setLogs] = useState<AuditLogsResponse | null>(null);
  const [tab, setTab] = useState<"results" | "audit">("results");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getResults(uid), getAuditLogs(uid)])
      .then(([r, l]) => {
        setResults(r);
        setLogs(l);
      })
      .finally(() => setLoading(false));
  }, [uid]);

  async function handleErrorDownload() {
    try {
      const blob = await downloadErrorReport(uid);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `migration_errors_${uid}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("No error report available.");
    }
  }

  if (loading) return <p>Loading results...</p>;
  if (!results) return null;

  return (
    <div>
      <h2>Import Results</h2>

      <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
        <span style={{ color: "green" }}>Imported: {results.imported}</span>
        <span style={{ color: "red" }}>Failed: {results.failed}</span>
        <span>Skipped: {results.skipped}</span>
        <span>Partial: {results.partially_imported}</span>
      </div>

      {results.failed > 0 && (
        <button onClick={handleErrorDownload} style={{ marginBottom: 16 }}>
          Download Error Report (CSV)
        </button>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button
          onClick={() => setTab("results")}
          style={{ fontWeight: tab === "results" ? "bold" : "normal" }}
        >
          Row Results
        </button>
        <button
          onClick={() => setTab("audit")}
          style={{ fontWeight: tab === "audit" ? "bold" : "normal" }}
        >
          Audit Log
        </button>
      </div>

      {tab === "results" && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f3f4f6" }}>
              <th style={{ padding: 8, textAlign: "left" }}>Row</th>
              <th style={{ padding: 8, textAlign: "left" }}>Reference</th>
              <th style={{ padding: 8, textAlign: "left" }}>Status</th>
              <th style={{ padding: 8, textAlign: "left" }}>Message</th>
            </tr>
          </thead>
          <tbody>
            {results.details.map((d) => (
              <tr key={d.row_number} style={{ borderBottom: "1px solid #e5e7eb" }}>
                <td style={{ padding: 8 }}>{d.row_number}</td>
                <td style={{ padding: 8 }}>{d.invoice_number ?? d.linked_record_uid ?? "—"}</td>
                <td style={{ padding: 8, color: STATUS_COLOR[d.status] }}>
                  {d.status}
                </td>
                <td style={{ padding: 8 }}>{d.message ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "audit" && logs && (
        <div>
          {logs.logs.map((log, i) => (
            <div
              key={i}
              style={{
                borderBottom: "1px solid #e5e7eb",
                padding: "8px 0",
                display: "flex",
                gap: 16,
              }}
            >
              <span style={{ color: "#6b7280", fontSize: 13 }}>
                {new Date(log.timestamp).toLocaleString()}
              </span>
              <span style={{ fontWeight: 500 }}>{log.actor}</span>
              <span>{log.action}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

---

## 13. Wizard State Management

### `hooks/useDataMigrationWizard.ts`

```ts
"use client";

import { useState, useCallback } from "react";
import type { MigrationStep, MigrationJobDetail } from "@/lib/types/datamigration";

const STEPS: MigrationStep[] = [
  "select_data_type",
  "upload_file",
  "map_fields",
  "preview_data",
  "validate_data",
  "review_impact",
  "confirm_import",
  "results_audit",
];

export function useDataMigrationWizard(initialJob?: MigrationJobDetail) {
  const [jobUid, setJobUid] = useState<string | null>(initialJob?.uid ?? null);
  const [job, setJob] = useState<MigrationJobDetail | null>(initialJob ?? null);
  const [currentStep, setCurrentStep] = useState<MigrationStep>(
    initialJob?.current_step ?? "select_data_type"
  );
  const [uploadedColumns, setUploadedColumns] = useState<string[]>([]);

  const stepIndex = STEPS.indexOf(currentStep);

  const advance = useCallback((nextStep?: MigrationStep) => {
    setCurrentStep((prev) => {
      if (nextStep) return nextStep;
      const idx = STEPS.indexOf(prev);
      return STEPS[Math.min(idx + 1, STEPS.length - 1)];
    });
  }, []);

  const goTo = useCallback((step: MigrationStep) => {
    setCurrentStep(step);
  }, []);

  return {
    jobUid,
    setJobUid,
    job,
    setJob,
    currentStep,
    stepIndex,
    totalSteps: STEPS.length,
    steps: STEPS,
    advance,
    goTo,
    uploadedColumns,
    setUploadedColumns,
  };
}
```

---

## 14. Wizard Shell Component

### `components/datamigration/MigrationWizard.tsx`

```tsx
"use client";

import { useDataMigrationWizard } from "@/hooks/useDataMigrationWizard";
import { getMigration } from "@/lib/api/datamigration";
import { SelectDataType } from "./steps/SelectDataType";
import { UploadFile } from "./steps/UploadFile";
import { MapFields } from "./steps/MapFields";
import { PreviewData } from "./steps/PreviewData";
import { ValidateData } from "./steps/ValidateData";
import { ReviewImpact } from "./steps/ReviewImpact";
import { ConfirmImport } from "./steps/ConfirmImport";
import { ResultsAudit } from "./steps/ResultsAudit";
import type { MigrationStep } from "@/lib/types/datamigration";

const STEP_LABELS: Record<MigrationStep, string> = {
  select_data_type: "Select Type",
  upload_file: "Upload",
  map_fields: "Map Fields",
  preview_data: "Preview",
  validate_data: "Validate",
  review_impact: "Review Impact",
  confirm_import: "Confirm",
  results_audit: "Results",
};

export function MigrationWizard() {
  const wizard = useDataMigrationWizard();

  async function refreshJob(uid: string) {
    const updated = await getMigration(uid);
    wizard.setJob(updated);
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      {/* Progress bar */}
      <div style={{ display: "flex", marginBottom: 32 }}>
        {wizard.steps.map((step, i) => (
          <div
            key={step}
            style={{
              flex: 1,
              textAlign: "center",
              padding: "8px 4px",
              borderBottom: `3px solid ${i <= wizard.stepIndex ? "#3b82f6" : "#e5e7eb"}`,
              color: i <= wizard.stepIndex ? "#3b82f6" : "#9ca3af",
              fontSize: 12,
              fontWeight: i === wizard.stepIndex ? 700 : 400,
            }}
          >
            {i + 1}. {STEP_LABELS[step]}
          </div>
        ))}
      </div>

      {/* Step content */}
      {wizard.currentStep === "select_data_type" && (
        <SelectDataType
          onCreated={async (uid) => {
            wizard.setJobUid(uid);
            await refreshJob(uid);
            wizard.advance();
          }}
        />
      )}

      {wizard.currentStep === "upload_file" && wizard.jobUid && wizard.job && (
        <UploadFile
          uid={wizard.jobUid}
          dataType={wizard.job.data_type}
          onUploaded={(cols) => {
            wizard.setUploadedColumns(cols);
            refreshJob(wizard.jobUid!).then(() => wizard.advance());
          }}
        />
      )}

      {wizard.currentStep === "map_fields" && wizard.jobUid && (
        <MapFields
          uid={wizard.jobUid}
          onMapped={() => refreshJob(wizard.jobUid!).then(() => wizard.advance())}
        />
      )}

      {wizard.currentStep === "preview_data" && wizard.jobUid && (
        <PreviewData
          uid={wizard.jobUid}
          onConfirmed={() => wizard.advance()}
        />
      )}

      {wizard.currentStep === "validate_data" && wizard.jobUid && (
        <ValidateData
          uid={wizard.jobUid}
          onValidated={() => refreshJob(wizard.jobUid!).then(() => wizard.advance())}
        />
      )}

      {wizard.currentStep === "review_impact" && wizard.jobUid && (
        <ReviewImpact
          uid={wizard.jobUid}
          onReviewed={() => refreshJob(wizard.jobUid!).then(() => wizard.advance())}
        />
      )}

      {wizard.currentStep === "confirm_import" && wizard.jobUid && wizard.job && (
        <ConfirmImport
          uid={wizard.jobUid}
          job={wizard.job}
          onImported={() => refreshJob(wizard.jobUid!).then(() => wizard.advance())}
        />
      )}

      {wizard.currentStep === "results_audit" && wizard.jobUid && (
        <ResultsAudit uid={wizard.jobUid} />
      )}
    </div>
  );
}
```

### Page Route

```tsx
// app/data-migration/new/page.tsx
import { MigrationWizard } from "@/components/datamigration/MigrationWizard";

export default function NewMigrationPage() {
  return <MigrationWizard />;
}
```

### Resume Existing Migration

```tsx
// app/data-migration/[uid]/page.tsx
import { getMigration } from "@/lib/api/datamigration";
import { MigrationWizard } from "@/components/datamigration/MigrationWizard";

// For server components — pass initial data to wizard
export default async function ResumeMigrationPage({
  params,
}: {
  params: { uid: string };
}) {
  const job = await getMigration(params.uid);
  return <MigrationWizardWithJob job={job} />;
}
```

Alternatively pass `initialJob` prop to `useDataMigrationWizard`:

```tsx
// hooks/useDataMigrationWizard.ts — already accepts initialJob
const wizard = useDataMigrationWizard(job); // resumes from job.current_step
```

---

## 15. Error Handling Patterns

### Classify API errors

```ts
// lib/api/client.ts — add to ApiError
export function isNotFound(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}

export function isUnprocessable(e: unknown): boolean {
  return e instanceof ApiError && e.status === 400;
}

export function getApiMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.body as { message?: string } | undefined;
    return body?.message ?? e.message;
  }
  return "An unexpected error occurred.";
}
```

### In-component pattern

```tsx
const [error, setError] = useState<string | null>(null);

async function doAction() {
  setError(null);
  try {
    await someApiCall();
  } catch (e) {
    setError(getApiMessage(e));
  }
}
```

### Handling "import not available yet"

Some data types return `import_available: false`. Handle at confirm step:

```ts
// The backend returns HTTP 400 with:
// { "message": "Import is not implemented yet for this migration type.", "import_available": false }

catch (e) {
  const body = (e as ApiError).body as { import_available?: boolean };
  if (body?.import_available === false) {
    setError("This data type is coming soon. Import is not yet available.");
  }
}
```

---

## 16. Template Download & Utilities

### Download helper (reusable)

```ts
// lib/utils/download.ts
export function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

### Usage anywhere

```ts
import { downloadTemplate } from "@/lib/api/datamigration";
import { triggerBlobDownload } from "@/lib/utils/download";

const blob = await downloadTemplate("invoices");
triggerBlobDownload(blob, "invoices_template.csv");
```

---

## Quick Reference: API Endpoints

| Step | Method | Path | Notes |
|------|--------|------|-------|
| List migrations | GET | `/data-migrations` | |
| Create migration | POST | `/data-migrations` | body: `{ data_type }` |
| Get detail | GET | `/data-migrations/{uid}` | |
| Get data types | GET | `/data-migrations/data-types` | |
| Download template | GET | `/data-migrations/templates/{data_type}/download` | returns CSV |
| Upload file | POST | `/data-migrations/{uid}/upload` | multipart/form-data |
| Preview | GET | `/data-migrations/{uid}/preview` | |
| Auto-map | POST | `/data-migrations/{uid}/auto-map` | |
| Save mappings | POST | `/data-migrations/{uid}/mapping` | |
| Validate | POST | `/data-migrations/{uid}/validate` | |
| Validation issues | GET | `/data-migrations/{uid}/validation-issues` | |
| Fix row | POST | `/data-migrations/{uid}/rows/{row_uid}/fix` | |
| Review impact | POST | `/data-migrations/{uid}/review-impact` | |
| Confirm import | POST | `/data-migrations/{uid}/confirm` | |
| Results | GET | `/data-migrations/{uid}/results` | |
| Error report | GET | `/data-migrations/{uid}/error-report` | returns CSV |
| Audit logs | GET | `/data-migrations/{uid}/audit-logs` | |

---

## Notes

- **Only `invoices`** has a fully working import. All other data types return `import_available: false` and will respond with a 400 on the confirm step. Show a "coming soon" message for those.
- **File formats supported:** CSV, XLSX/XLS, JSON array.
- **Auth:** All endpoints require a valid user session. The backend scopes results to `request.user.get_active_company()`, so the correct company must be active.
- **Async import:** The confirm endpoint may return `status: "in_progress"`. Poll `GET /{uid}` every 3 seconds until status becomes `completed`, `partially_completed`, or `failed`. Add a timeout guard (5 minutes max).
- **Resuming:** If the user navigates away mid-wizard, use the job's `current_step` field to resume from the right step.
