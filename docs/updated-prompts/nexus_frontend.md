# Economic Nexus — Frontend Integration Guide

What the frontend needs to build to consume the Economic Nexus backend. The
module **monitors** each company's US-state sales against every state's sales-tax
registration thresholds and reports a per-state verdict, alerts, an agency
handoff, and three reports. It never posts to the ledger — it's a monitoring /
advisory surface.

---

## 0. Conventions (read first)

- **Base URL:** all endpoints below are under `/api/v1/we`. Reports are under
  `/api/v1/we/reports`.
- **Auth / active company:** standard `/we` auth (bearer JWT). The active company
  is taken from the JWT's company claim — **no extra header per request**. Switch
  company the same way you do everywhere else in the app.
- **Feature gate:** every `/nexus/*` endpoint requires the **`is_agency_tax`**
  subscription feature. If the company doesn't have it, the API returns **403** —
  hide/disable the whole Nexus area for those companies. The **reports** instead
  require the **`is_standard_report`** feature plus the **`view_reports`**
  permission.
- **Percentages are fractions.** `pct_of_sales_threshold: 0.95` means **95 %**.
  Multiply by 100 for display. They can exceed 1.0 (e.g. `1.20` = 120 % of
  threshold) and are `null` when the state has no such threshold.
- **Money fields** are plain numbers (floats), already summed for the governing
  measurement window.
- Data is **precomputed**. The dashboard/detail read stored rows; they do not
  re-measure sales on each call. Freshness is `last_evaluated_at`. Use the
  **Recalculate** action (or the nightly job) to refresh.

---

## 1. Enums (single source of truth for badges/labels)

**`status`** (per-state verdict — the main thing to render):

| value | meaning | suggested UI |
|---|---|---|
| `NOT_APPROACHING` | comfortably below threshold | grey / neutral |
| `APPROACHING` | at/above the warning fraction (default 80 %), not yet met | amber / warning |
| `MET` | threshold crossed — **action needed**, not yet registered | red / danger |
| `REGISTERED` | user marked physical nexus or registered | blue / done |
| `NOT_APPLICABLE` | state has no statewide sales tax (DE, MT, NH, OR) | muted / hidden by default |

**`combination_logic`** (how the state's threshold is tested):
`SALES_ONLY` (sales $ only) · `OR` (sales $ **or** txn count) · `AND` (sales $
**and** txn count) · `NONE` (no sales tax).
> AND-state note: in an `AND` state (e.g. NY $500k **and** 100 txns) a high
> transaction count **alone** never means nexus — both must be met. Don't render
> "close" purely off txn %.

**`alert_type`:** `APPROACHING` · `CROSSED`.
**`filing_frequency`:** `MONTHLY` · `QUARTERLY` · `ANNUAL`.
**`registration_status`:** `NOT_STARTED` · `REGISTERED`.
**`registration_type`:** `ECONOMIC` · `PHYSICAL_MANUAL`.

---

## 2. Screens to build

1. **Nexus Dashboard** — table of states with verdict + progress bars. (§3.1)
2. **State Detail drawer/page** — one state's rule, measured activity, and the
   registration / agency-handoff actions. (§3.2, §4)
3. **Alerts worklist** — approaching/crossed alerts with acknowledge. (§5)
4. **Settings** — the warning fraction. (§6)
5. **Reports** — Exposure, Approaching-Risk, Threshold-History (list + PDF). (§7)

---

## 3. Dashboard & detail

### 3.1 `GET /nexus/dashboard`

Returns every tracked state, sorted with REGISTERED/MET/APPROACHING first.

```json
{
  "count": 45,
  "rows": [
    {
      "state_code": "AZ",
      "state_name": "Arizona",
      "has_sales_tax": true,
      "sales_threshold": 100000.0,
      "txn_threshold": null,
      "combination_logic": "SALES_ONLY",
      "includable_sales_basis": "GROSS",
      "measurement_period_type": "CURRENT_OR_PREVIOUS_YEAR",
      "window_start": "2026-01-01",
      "window_end": "2026-07-07",
      "sales_amount": 120000.0,
      "taxable_sales_amount": 118000.0,
      "txn_count": 340,
      "pct_of_sales_threshold": 1.2,
      "pct_of_txn_threshold": null,
      "threshold_met": true,
      "status": "MET",
      "threshold_met_date": "2026-06-01",
      "last_evaluated_at": "2026-07-07T02:00:00Z",
      "registration_type": null,
      "registration_status": "NOT_STARTED",
      "sales_tax_permit_number": null,
      "filing_frequency": null,
      "collection_start_date": null,
      "tax_agency_uid": null
    }
  ]
}
```

UI hints:
- Progress bar = `pct_of_sales_threshold` (and a second bar for
  `pct_of_txn_threshold` when it's non-null, i.e. OR/AND states). Cap the bar at
  100 % visually but show the real number (can be >100 %).
- Show `sales_amount` / `sales_threshold` under the bar, and
  `txn_count` / `txn_threshold` when a txn threshold exists.
- If `count` is 0, the company has never been recalculated — show an empty state
  with a **Recalculate** button (§3.3).
- `NOT_APPLICABLE` rows can be collapsed behind a "show states without sales tax"
  toggle.

### 3.2 `GET /nexus/state/{STATE_CODE}`

Same row shape as one dashboard row (all rule + activity + registration fields).
`STATE_CODE` is case-insensitive (`az` or `AZ`). **404** if that state has never
been computed for the company — surface "Run a recalculation to populate it."

### 3.3 `POST /nexus/recalculate`

Recompute the active company now (button on the dashboard). Runs the same engine
as the nightly job.

```json
{ "detail": "Nexus recalculated.", "evaluated_states": 47, "unattributed_sales": 5400.0 }
```

- **`unattributed_sales`** = sales that couldn't be mapped to a state (missing
  customer address/province). If > 0, show a hint: "$5,400 of sales couldn't be
  attributed to a state — add customer addresses to include them." These are
  **not** counted toward any state's threshold.
- This call is synchronous. Show a spinner; on success refetch the dashboard.

---

## 4. Registration & agency handoff (State Detail actions)

Three actions, all keyed by state code. Bodies are all-optional; send what the
user fills in.

**Shared request body** (`application/json`):
```json
{
  "collection_start_date": "2026-07-01",          // optional, ISO date
  "filing_frequency": "QUARTERLY",                // optional: MONTHLY|QUARTERLY|ANNUAL
  "sales_tax_permit_number": "AZ-123456",         // optional string
  "mark_registered": true                          // start-agency-setup only
}
```

Guardrails for all three: **404** if the state code is unknown; **400** if the
state has no statewide sales tax (`NONE`). After any of them the backend
recomputes, so the returned/next dashboard status is authoritative — **refetch
the dashboard (or the state) after each call.**

### 4.1 `POST /nexus/state/{STATE}/mark-nexus`
Mark **physical / manual** nexus (e.g. an office or warehouse). Flips the state to
`REGISTERED` on the dashboard and **suppresses its alerts**. Returns
`{ "detail": "...", ...registration fields }`.

### 4.2 `DELETE /nexus/state/{STATE}/mark-nexus`
Remove the mark/registration (de-register). Returns **204**. The state reverts to
its true numeric status (e.g. back to `MET`), and if it's over threshold a fresh
`CROSSED` alert will be raised on the next recompute.

### 4.3 `POST /nexus/state/{STATE}/start-agency-setup`
Records the **handoff to the Sales Tax module** (registration intent, links an
existing agency for the state if one already exists) and returns a `resume_url`:

```json
{
  "detail": "Agency setup started.",
  "resume_url": "/sales-tax/agencies?state=AZ",
  "registration_type": "ECONOMIC",
  "registration_status": "NOT_STARTED",
  "...": "..."
}
```

- **Navigate the user to `resume_url`** — that Sales Tax screen is where the
  agency + tax rates are actually created. This endpoint does **not** create the
  agency or turn on rate calculation.
- `mark_registered: true` sets the state to `REGISTERED` immediately (use when the
  user confirms they've already registered); otherwise it stays `NOT_STARTED`
  until Sales Tax completes.

---

## 5. Alerts

### 5.1 `GET /nexus/alerts`
Paginated (standard page-number pagination: `?page=` for the page, `?limit=` for
page size, max 100). Filter the open worklist with **`?acknowledged=false`** (or
`true` for the archive).

```json
{
  "count": 3,
  "results": [
    {
      "uid": "a1b2c3d4-...",
      "state_code": "AZ",
      "alert_type": "CROSSED",
      "threshold_pct_at_alert": 1.2,
      "triggered_at": "2026-06-01T02:00:00Z",
      "acknowledged": false,
      "acknowledged_at": null
    }
  ]
}
```

Render `CROSSED` as danger, `APPROACHING` as warning. Each fires **once per
episode** (a state that hovers over the line won't spam). Users also receive an
in-app notification (kinds `NEXUS_THRESHOLD_CROSSED` /
`NEXUS_THRESHOLD_APPROACHING`, `model_kind: "NEXUS"`) — deep-link those to the
state detail.

### 5.2 `POST /nexus/alerts/{uid}/acknowledge`
Marks the alert acknowledged (idempotent). Returns the updated alert object.
Optimistically move it off the open worklist.

---

## 6. Settings

- `GET /nexus/settings` → `{ "warning_fraction": 0.8 }`
- `PATCH /nexus/settings` body `{ "warning_fraction": 0.75 }` → echoes the saved
  value.

`warning_fraction` is the point (as a fraction, 0–1) at which a state flips to
`APPROACHING` and an approaching alert can fire — default **0.80** (80 %). Present
it as a percentage slider/input.

---

## 7. Reports

Three read-only reports under `/api/v1/we/reports/nexus`:

| report | path |
|---|---|
| Economic Nexus Exposure | `/reports/nexus/exposure` |
| Approaching-Risk | `/reports/nexus/approaching-risk` |
| Threshold-History (audit trail) | `/reports/nexus/threshold-history` |

Each supports the **standard report query pattern** (same as other reports in the
app):

- **Default** (`GET` with no special query) → full JSON:
  ```json
  { "as_of": "2026-07-07", "rows": [ ... ], "total": { ... } }
  ```
- **`?keywords=overview`** → just the summary: `{ "as_of", "total" }`. Use for
  KPI cards without pulling all rows.
- **`?is_pdf=true`** → generates a PDF and returns `{ "file_uid", "url" }`;
  open/download `url`.

Gate: `is_standard_report` feature + `view_reports` permission (else **403**).

**Row shapes:**

*Exposure* & *Approaching-Risk* rows:
`state_code, state_name, window_start, window_end, sales_amount,
sales_threshold, pct_of_sales_threshold, txn_count, txn_threshold,
pct_of_txn_threshold, status, threshold_met_date, registration_status`.
`total`: `{ "met": n, "approaching": n, "registered": n }`.
- Exposure = every tracked state. Approaching-Risk = only `APPROACHING` states,
  ordered by whichever of the two percentages is **closest** to 100 % (a state
  95 % of the way there via transaction count outranks one at 82 % of the sales
  threshold), `total` = `{ "count": n }`.

*Threshold-History* rows:
`state_code, state_name, alert_type, threshold_pct_at_alert, triggered_at,
acknowledged_at`. `total`: `{ "crossed": n }`. This is the audit trail of every
alert ever raised — most recent first.

> Reports read the precomputed rows/alerts. If the data looks stale, run
> **Recalculate** (§3.3) first.

---

## 8. Suggested build order

1. **Dashboard** (`GET /dashboard`) + **Recalculate** button + empty state.
2. **State Detail** drawer (`GET /state/{code}`) with the three registration
   actions (§4) — refetch after each.
3. **Alerts** worklist + acknowledge, plus wiring the two notification kinds.
4. **Settings** (warning fraction).
5. **Reports** (list + overview cards + PDF export).

## 9. Error handling cheat-sheet

| status | when | UI |
|---|---|---|
| 403 | company lacks `is_agency_tax` (nexus) / `is_standard_report`+`view_reports` (reports) | hide/disable the feature, show upsell |
| 404 | state detail before first recompute; unknown state code | prompt to Recalculate |
| 400 | mark-nexus / start-agency-setup on a no-sales-tax state | disable those actions for `NOT_APPLICABLE` states |
