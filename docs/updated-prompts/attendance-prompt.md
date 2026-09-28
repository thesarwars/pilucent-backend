# Attendance — Backend Changes & Frontend Integration

Status of the **Bulk Manual Attendance** work and exactly what the frontend needs to wire up.
Pairs with `Manual Attendance - Backend Algorithm Prompt.md` and `Bulk Manual Attendance - Page Spec.md`.

---

## 1. What changed in the backend (shipped)

The first vertical slice of the manual-attendance subsystem — the **"mark the whole team for one day"** flow the Bulk page is built around — is implemented and deployed.

| Change | File |
|---|---|
| Added **`HALF_DAY`** to the attendance status enum (the page's "H" mark) | `attendanceio/choices.py` |
| **Unique constraint** on `Attendance (employee, date, company)` + migration `0017` (dedupes any pre-existing duplicates first) so manual marking **upserts** instead of duplicating | `attendanceio/models.py`, `attendanceio/migrations/0017_*` |
| **Shared pure derivation service** `derive_attendance()` — grace-aware lateness, break = `lunch+tiffin`, half-day downgrade, daily OT, off-day clearing, auto-fill from shift, midnight-cross, `needs_review` | `attendanceio/django_rest/helpers/derivation.py` |
| **Context resolver** (holiday → leave → working day, batched for a whole team in 2 queries) | `attendanceio/django_rest/helpers/context.py` |
| **Two-phase bulk endpoints** (preview + commit) with merge precedence, per-row outcomes, live summary counts | `weapi/django_rest/serializers/attendance_bulk.py`, `weapi/django_rest/views/attendances.py`, `weapi/django_rest/urls/attendances.py` |
| 12 unit tests for the derivation contract | `attendanceio/tests.py` |

**Not built yet (deferred — see §8)**: single `/attendance/manual` upsert, soft-delete/`void`, locked-period guard, audit pointer in the response, date-range bulk, FLSA weekly OT.

---

## 2. New endpoints

Base: `/api/v1/we/attendances` (admin/"we" API). **Auth:** the normal workspace bearer token — the request must carry the JWT whose `company_id` claim selects the active company; everything is scoped to that company.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/we/attendances/bulk/preview` | **Dry-run.** Derives every row and returns per-row outcomes + summary counts. **Writes nothing.** |
| `POST` | `/api/v1/we/attendances/bulk/commit` | **Transactional upsert** of the derived rows. Same request body as preview. |

Existing endpoints (unchanged, still available):
`GET/POST /api/v1/we/attendances` (list / bare single create), `GET/PATCH/DELETE /api/v1/we/attendances/{uid}`, `GET/POST /api/v1/we/attendances/processes`, `GET/POST /api/v1/we/attendances/punch-data`.

---

## 3. Request body (identical for preview and commit)

```jsonc
{
  "date": "2026-06-23",                 // required. YYYY-MM-DD. Must NOT be in the future.
  "defaults": {                          // optional — the "Mark everyone" / quick-fill values
    "status": "PRESENT",                 // optional, see §5 for allowed values
    "check_in": "09:00",                 // optional, "HH:MM" or "HH:MM:SS"
    "check_out": "17:00",                // optional
    "note": "Quick note for everyone"    // optional
  },
  "rows": [                              // optional — per-employee overrides
    {
      "employee_uid": "0b1f…-uuid",      // required per row (Employee.uid)
      "status": "LATE_ARRIVAL",          // optional; falls back to defaults.status, then derived
      "check_in": "09:30",               // optional
      "check_out": "17:00",              // optional
      "note": "Traffic"                  // optional
    }
  ]
}
```

**Rules**
- You must send `defaults` and/or `rows` (at least one). Sending neither → `400`.
- **Scope of who gets marked:**
  - If `defaults` is present → **all ACTIVE employees** in the company are processed, each overridable by its matching `rows` entry. (This is "Mark everyone".)
  - If `defaults` is absent → only the employees listed in `rows` are processed.
- **Merge precedence (per field): row value → `defaults` value → derived.** A field present on the row wins even if empty (so an `ABSENT` row clears its times regardless of defaults).
- `date` in the future → `400 {"date": ["Attendance date cannot be in the future."]}`.

---

## 4. Response body (preview and commit)

```jsonc
{
  "date": "2026-06-23",
  "committed": false,                    // false for /preview, true for /commit
  "summary": {
    "counts": {                          // use these for the 5 summary cards
      "PRESENT": 12, "ABSENT": 2, "LATE_ARRIVAL": 3,
      "HALF_DAY": 1, "HOLIDAY": 0, "LEAVE": 1
    },
    "marked": 17,                        // rows the admin explicitly gave a status (for "{n} of {m} marked")
    "total": 19,                         // employees in scope (for progress bar denominator)
    "needs_review": 1,                   // rows flagged (e.g. PRESENT on a holiday/leave day)
    "errors": 1                          // rows that failed validation
  },
  "rows": [
    {
      "employee_uid": "0b1f…",
      "employee_id": "EMP-001",
      "employee_name": "Jane Doe",
      "shift_uid": "8a2c…",              // null if employee has no shift
      "status": "LATE_ARRIVAL",          // DERIVED final status (may differ from what you sent)
      "check_in": "09:30:00",            // normalized; null for off-days
      "check_out": "17:00:00",           // null for off-days
      "worked_hours": 6.5,               // hours, net of break
      "late_mins": 15,                   // minutes, grace already applied
      "ot_hours": 0.0,                   // daily overtime, hours
      "break_mins": 60,                  // break used (defaults to shift lunch+tiffin)
      "needs_review": false,             // true => surface a warning chip
      "note": "Traffic",
      "is_explicit": true,               // whether the admin set the status (vs auto-derived)
      "warnings": [],                    // human-readable strings, e.g. auto-fill / clamp notes
      "error": null                      // string if this row failed; the rest of the batch still ran
    }
    // …one entry per scoped employee, plus error entries for unknown/inactive employee_uids
  ]
}
```

**Important:** the backend **derives** the final `status`, times, and numbers — they may not equal what you sent. Examples: a `PRESENT` row with a short span comes back `HALF_DAY`; a `PRESENT` row arriving past grace comes back `LATE_ARRIVAL`; an `ABSENT`/`HOLIDAY` row comes back with `check_in/out = null` and zeroed hours. **Render the page from the response**, don't assume your input echoes back.

Error rows (employee not found / not active in this company) appear in `rows` with `error` set and `status: null` — never silently dropped. Check `summary.errors`.

---

## 5. Status vocabulary & the P / A / L / H / O mapping

Page button → backend status:

| Page button | `status` value |
|---|---|
| **P** Present | `PRESENT` |
| **A** Absent | `ABSENT` |
| **L** Late | `LATE_ARRIVAL` |
| **H** Half day | `HALF_DAY` |
| **O** Holiday | `HOLIDAY` |

Also accepted by the API (not on the 5-button group, but valid to send): `LEAVE`, `WEEKEND`, `EARLY_DEPARTURE`, `SPECIAL`. Anything else → `400`.

Off-day statuses (`ABSENT`, `HOLIDAY`, `WEEKEND`, `LEAVE`, `SPECIAL`) automatically **clear** check-in/out and zero worked/late/ot — so disable/dim the time inputs for those marks (matches the Page Spec).

---

## 6. Derivation behavior the UI should expect

So the frontend knows why a response looks the way it does:

- **Auto-fill:** a presence status sent with **no times** is auto-filled from the shift (PRESENT → shift in/out; HALF_DAY → in → in+half-day; LATE → in+grace+1m). A `warnings` entry says so.
- **Lateness:** `late_mins = max(0, minutes_after_shift_start − grace)`.
- **Worked hours:** `(gross − break)/60`, rounded to 2 dp; `break` defaults to the shift's `lunch_time + tiffin_time` (override per row not exposed in this slice).
- **Half-day downgrade:** a PRESENT/LATE day whose worked hours ≤ half the shift's regular hours comes back `HALF_DAY`.
- **Overtime:** `ot_hours = max(0, worked − regular_hours)` (daily only; weekly/FLSA is payroll's job, not here).
- **`needs_review = true`** when a presence mark lands on an expected holiday/leave day — show a review chip; it does **not** block commit.

---

## 7. Recommended frontend flow

1. Render the team table; the **live summary + progress bar can be computed client-side** as the admin marks (no server call needed while editing).
2. On **Save attendance**:
   - (Recommended) `POST /bulk/preview` first → show a confirmation using `summary` (counts, `needs_review`, `errors`) and any per-row `warnings`. This is a safe dry-run.
   - Then `POST /bulk/commit` with the same body to persist. Re-render from its `rows`/`summary`.
   - (Simplest) Skip preview and call `/bulk/commit` directly — it returns the same shape.
3. Build the request from the table:
   - "Mark everyone present/absent/holiday" preset → set `defaults.status`.
   - Quick-fill In/Out/Note "Apply to all" → set `defaults.check_in/check_out/note`. "Apply to N selected" → put those on the selected `rows`.
   - Per-row marks/times/notes → `rows[]` (only the rows the admin touched need to be sent when `defaults` is present).
4. After commit, navigate back to the Attendance list (the records now exist as upserts for that date).

### Minimal example

Mark everyone present, override two people:
```jsonc
POST /api/v1/we/attendances/bulk/commit
{
  "date": "2026-06-23",
  "defaults": { "status": "PRESENT", "check_in": "09:00", "check_out": "17:00" },
  "rows": [
    { "employee_uid": "…amad", "status": "ABSENT", "note": "Sick" },
    { "employee_uid": "…ben",  "status": "LATE_ARRIVAL", "check_in": "09:40" }
  ]
}
```

---

## 8. Not available yet (don't build against these)

- **Single manual upsert** `POST /attendance/manual` — not built. For one person, send a `bulk` body with a single `rows` entry. (The existing `POST /attendances` create is *bare* — it does NOT derive status/hours — avoid it for manual marking.)
- **Soft delete / void** — `DELETE /attendances/{uid}` is a hard delete; there's no `/void` yet.
- **Locked-period / 423** — no payroll-lock guard yet, so no `423` to handle.
- **Date-range bulk** — single `date` only (no `{fromDate,toDate}`).
- **Audit pointer** in the response — not included yet.
- The response has no `late_mins`/`ot_hours` *stored* on the record yet; they're computed and returned by these endpoints but the list endpoint still derives late/OT its own (legacy) way.

---

## 9. Validation / error handling cheatsheet

| Situation | Response |
|---|---|
| `date` missing | `400 {"date": ["This field is required."]}` |
| `date` in the future | `400 {"date": ["Attendance date cannot be in the future."]}` |
| neither `defaults` nor `rows` | `400` (non-field error) |
| invalid `status` value | `400` |
| `employee_uid` not found / inactive in company | row appears in `rows` with `error` set, `summary.errors` incremented (batch still succeeds) |
| no active company in token | `403 {"message": "No active company in context."}` |
| commit success | `200` with `committed: true` |
