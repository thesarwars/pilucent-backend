# Payroll Tax Config — Backend Storage Design

**Goal:** move the hard-coded 2026 tax rates in [`SalaryProcess.ts`](./SalaryProcess.ts)
out of the frontend and serve them from the backend, **keeping the exact same
data-structure shape** so the calculation code barely changes. Each new tax year
becomes a data edit on the server instead of a code deploy.

This file is the spec. It covers: what moves vs. what stays, the JSON contract,
the database model, the API, the frontend loader, and the rollout plan.

---

## 1. What is static today

Everything the calculators read lives in one object, `CONFIG`
([`SalaryProcess.ts:91`](./SalaryProcess.ts#L91)), plus the exported constants above it
([`SalaryProcess.ts:25-89`](./SalaryProcess.ts#L25)). Shape:

```
CONFIG
├─ year: 2026
├─ federal
│   ├─ ssRate, ssWageBase, medicareRate, addMedicareRate, addMedicareThreshold
│   ├─ futaRate, futaGrossRate, futaDefaultCreditRate, futaWageBase
│   ├─ standardDeduction            { single, married, mfj, mfs, hoh }
│   ├─ brackets                     { single, mfs, married, mfj, hoh }  → [lower, upper, rate][]
│   ├─ supplementalRate, highSupplementalRate, highSupplementalThreshold
│   ├─ percentageMethodTables
│   │   ├─ standard { married, single, hoh }  → Pub15TRow[]
│   │   └─ step2    { married, single, hoh }  → Pub15TRow[]
│   └─ step4bAdjustmentWhenStep2Unchecked { married, single, hoh, mfj, mfs }
├─ mn
│   ├─ standardDeduction, allowanceValue, supplementalRate
│   ├─ paidLeaveWageBase, paidLeaveEmployeeRate, paidLeaveEmployerStandardRate, paidLeaveEmployerSmallRate
│   ├─ uiWageBase, uiBaseTaxRate, uiAdditionalAssessmentRate,
│   │   uiFederalLoanInterestAssessmentRate, uiWorkforceDevelopmentFeeRate, uiDefaultRate
│   └─ brackets                     { single, married, mfj, mfs, hoh }  → [lower, upper, rate][]
└─ ny
    ├─ exemptionBase, exemptionPerAllowance, stateSupplementalRate
    ├─ uiWageBase, uiDefaultRate, uiNewEmployerRate, uiLowestRate, uiHighestRate, rsfRate
    ├─ pflRate, pflAnnualCap, dblWeeklyCap, dblRate
    ├─ nysAnnualMethodII            { single, married }  → [lower, upper, subtract, rate, add][]
    ├─ nycExemptionBase, nycExemptionPerAllowance, nycSupplementalRate
    ├─ nycAnnualMethodII            { single, married }  → [lower, upper, subtract, rate, add][]
    └─ mctmtThreshold, mctmtRates   { zone1, zone2 }     → [lower, upper, rate][]
```

### Row/tuple formats (must be preserved exactly)

| Table | Tuple | Read by |
|-------|-------|---------|
| `brackets` (federal/mn), `mctmtRates` | `[lower, upper, rate]` | `progressiveTax()` ([L305](./SalaryProcess.ts#L305)) |
| `nysAnnualMethodII`, `nycAnnualMethodII` | `[lower, upper, subtract, rate, add]` | `tableTax()` ([L322](./SalaryProcess.ts#L322)) |
| `percentageMethodTables.*` | `{ atLeast, lessThan, subtract, rate, baseTax }` | `pub15tScheduleTax()` ([L826](./SalaryProcess.ts#L826)) |
| `standardDeduction`, `exemptionBase`, `step4b…` | `{ single, married, mfj, mfs, hoh }` | direct key lookup |

---

## 2. What moves to the backend vs. what stays on the employee

**Critical separation.** There are two kinds of numbers in this file:

1. **Statutory / system config** — identical for every company: IRS Pub. 15-T
   tables, wage bases, SS/Medicare/FUTA rates, NYS/NYC Method II schedules,
   MCTMT, MN/NY brackets, and the *system-default* UI rates. **These move to the
   backend, keyed by tax year.**
2. **Employer-specific experience-rated values** — the NY DOL rate-notice UI rate,
   the MN Tax Rate Determination rate, per-employee W-4 data and exemptions.
   **These already live on the employee/company tax record** (`taxes`,
   `holding_status`, `exempt_fields`, `ui_rate`, …) and are consumed by
   `buildFederalW4InputsFromTaxRecord()`, `getTaxExemptions()`, etc. **Do not move
   these into the year config.** The year config only supplies the *fallback
   default* (e.g. `ny.uiDefaultRate`) used when the tax record has no value —
   exactly as the code comments already say ("call sites should pass the
   employer's rate-notice value").

So the backend resource is **one document per tax year**, tenant-independent
(no `company_uid`). It is reference data, like a currency table.

---

## 3. Storage design — recommended: one JSON document per year

The data is deeply nested and read *all at once* per payroll run. Normalising it
into dozens of relational tables buys nothing for how it's consumed and forces
you to re-assemble the `CONFIG` shape on every request. **Store the whole tree as
one JSON (JSONB) document keyed by `year`.** One row, one `GET`, exact shape.

> A fully normalised alternative is described in §9 for teams that need
> row-level auditing/reporting on individual brackets. For this app the JSON
> document is the right call.

### 3.1 Django model (matches the `/we` DRF stack)

```python
# payroll/models.py
from django.db import models

class PayrollTaxConfig(models.Model):
    """Statutory payroll tax tables & system-default rates for one tax year.
    Tenant-independent reference data — NOT per company."""

    year = models.PositiveIntegerField(unique=True, db_index=True)   # 2026
    status = models.CharField(
        max_length=16,
        choices=[("DRAFT", "Draft"), ("PUBLISHED", "Published")],
        default="DRAFT",
    )
    # Optional finer-grained effective window; year is enough for now.
    effective_from = models.DateField(null=True, blank=True)         # 2026-01-01
    effective_to = models.DateField(null=True, blank=True)           # 2026-12-31

    data = models.JSONField()          # the CONFIG tree (see §4). JSONB on Postgres.
    source_notes = models.TextField(blank=True, default="")          # "IRS Pub 15-T 2026; NY DOL ..."
    version = models.PositiveIntegerField(default=1)                 # bump on every edit

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return f"PayrollTaxConfig {self.year} v{self.version} ({self.status})"
```

### 3.2 Equivalent raw SQL (Postgres)

```sql
CREATE TABLE payroll_tax_config (
    id             BIGSERIAL PRIMARY KEY,
    year           INTEGER NOT NULL UNIQUE,
    status         VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
    effective_from DATE,
    effective_to   DATE,
    data           JSONB NOT NULL,
    source_notes   TEXT NOT NULL DEFAULT '',
    version        INTEGER NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_payroll_tax_config_year ON payroll_tax_config (year);
```

**Why JSONB and not a nested-table schema:** the consumer wants the entire tree
in one shot; there are no queries like "all brackets over 24%". JSONB gives exact
shape parity, atomic year edits, trivial versioning, and one round trip.

---

## 4. The JSON contract (`data` column = API response body)

This is the canonical 2026 seed. **It is byte-for-byte the `CONFIG` object**, with
one transform (see §5): every `Infinity` upper bound is serialized as `null`.
The frontend loader converts `null` back to `Infinity` on the way in.

```json
{
  "year": 2026,
  "federal": {
    "ssRate": 0.062,
    "ssWageBase": 184500,
    "medicareRate": 0.0145,
    "addMedicareRate": 0.009,
    "addMedicareThreshold": 200000,
    "futaRate": 0.006,
    "futaGrossRate": 0.06,
    "futaDefaultCreditRate": 0.054,
    "futaWageBase": 7000,
    "standardDeduction": { "single": 16100, "married": 32200, "mfj": 32200, "mfs": 16100, "hoh": 24150 },
    "brackets": {
      "single":  [[0,12400,0.10],[12400,50400,0.12],[50400,105700,0.22],[105700,201775,0.24],[201775,256225,0.32],[256225,640600,0.35],[640600,null,0.37]],
      "mfs":     [[0,12400,0.10],[12400,50400,0.12],[50400,105700,0.22],[105700,201775,0.24],[201775,256225,0.32],[256225,384350,0.35],[384350,null,0.37]],
      "married": [[0,24800,0.10],[24800,100800,0.12],[100800,211400,0.22],[211400,403550,0.24],[403550,512450,0.32],[512450,768700,0.35],[768700,null,0.37]],
      "mfj":     [[0,24800,0.10],[24800,100800,0.12],[100800,211400,0.22],[211400,403550,0.24],[403550,512450,0.32],[512450,768700,0.35],[768700,null,0.37]],
      "hoh":     [[0,17700,0.10],[17700,67450,0.12],[67450,105700,0.22],[105700,201775,0.24],[201775,256200,0.32],[256200,640600,0.35],[640600,null,0.37]]
    },
    "supplementalRate": 0.22,
    "highSupplementalRate": 0.37,
    "highSupplementalThreshold": 1000000,
    "percentageMethodTables": {
      "standard": {
        "married": [
          {"atLeast":0,"lessThan":19300,"subtract":0,"rate":0,"baseTax":0},
          {"atLeast":19300,"lessThan":44100,"subtract":19300,"rate":0.10,"baseTax":0},
          {"atLeast":44100,"lessThan":120100,"subtract":44100,"rate":0.12,"baseTax":2480},
          {"atLeast":120100,"lessThan":230700,"subtract":120100,"rate":0.22,"baseTax":11600},
          {"atLeast":230700,"lessThan":422850,"subtract":230700,"rate":0.24,"baseTax":35932},
          {"atLeast":422850,"lessThan":531750,"subtract":422850,"rate":0.32,"baseTax":82048},
          {"atLeast":531750,"lessThan":788000,"subtract":531750,"rate":0.35,"baseTax":116896},
          {"atLeast":788000,"lessThan":null,"subtract":788000,"rate":0.37,"baseTax":206583.50}
        ],
        "single": [
          {"atLeast":0,"lessThan":7500,"subtract":0,"rate":0,"baseTax":0},
          {"atLeast":7500,"lessThan":19900,"subtract":7500,"rate":0.10,"baseTax":0},
          {"atLeast":19900,"lessThan":57900,"subtract":19900,"rate":0.12,"baseTax":1240},
          {"atLeast":57900,"lessThan":113200,"subtract":57900,"rate":0.22,"baseTax":5800},
          {"atLeast":113200,"lessThan":209275,"subtract":113200,"rate":0.24,"baseTax":17966},
          {"atLeast":209275,"lessThan":263725,"subtract":209275,"rate":0.32,"baseTax":41024},
          {"atLeast":263725,"lessThan":648100,"subtract":263725,"rate":0.35,"baseTax":58448},
          {"atLeast":648100,"lessThan":null,"subtract":648100,"rate":0.37,"baseTax":192979.25}
        ],
        "hoh": [
          {"atLeast":0,"lessThan":15550,"subtract":0,"rate":0,"baseTax":0},
          {"atLeast":15550,"lessThan":33250,"subtract":15550,"rate":0.10,"baseTax":0},
          {"atLeast":33250,"lessThan":83000,"subtract":33250,"rate":0.12,"baseTax":1770},
          {"atLeast":83000,"lessThan":121250,"subtract":83000,"rate":0.22,"baseTax":7740},
          {"atLeast":121250,"lessThan":217300,"subtract":121250,"rate":0.24,"baseTax":16155},
          {"atLeast":217300,"lessThan":271750,"subtract":217300,"rate":0.32,"baseTax":39207},
          {"atLeast":271750,"lessThan":656150,"subtract":271750,"rate":0.35,"baseTax":56631},
          {"atLeast":656150,"lessThan":null,"subtract":656150,"rate":0.37,"baseTax":191171}
        ]
      },
      "step2": {
        "married": [
          {"atLeast":0,"lessThan":16100,"subtract":0,"rate":0,"baseTax":0},
          {"atLeast":16100,"lessThan":28500,"subtract":16100,"rate":0.10,"baseTax":0},
          {"atLeast":28500,"lessThan":66500,"subtract":28500,"rate":0.12,"baseTax":1240},
          {"atLeast":66500,"lessThan":121800,"subtract":66500,"rate":0.22,"baseTax":5800},
          {"atLeast":121800,"lessThan":217875,"subtract":121800,"rate":0.24,"baseTax":17966},
          {"atLeast":217875,"lessThan":272325,"subtract":217875,"rate":0.32,"baseTax":41024},
          {"atLeast":272325,"lessThan":400450,"subtract":272325,"rate":0.35,"baseTax":58448},
          {"atLeast":400450,"lessThan":null,"subtract":400450,"rate":0.37,"baseTax":103291.75}
        ],
        "single": [
          {"atLeast":0,"lessThan":8050,"subtract":0,"rate":0,"baseTax":0},
          {"atLeast":8050,"lessThan":14250,"subtract":8050,"rate":0.10,"baseTax":0},
          {"atLeast":14250,"lessThan":33250,"subtract":14250,"rate":0.12,"baseTax":620},
          {"atLeast":33250,"lessThan":60900,"subtract":33250,"rate":0.22,"baseTax":2900},
          {"atLeast":60900,"lessThan":108938,"subtract":60900,"rate":0.24,"baseTax":8983},
          {"atLeast":108938,"lessThan":136163,"subtract":108938,"rate":0.32,"baseTax":20512},
          {"atLeast":136163,"lessThan":328350,"subtract":136163,"rate":0.35,"baseTax":29224},
          {"atLeast":328350,"lessThan":null,"subtract":328350,"rate":0.37,"baseTax":96489.63}
        ],
        "hoh": [
          {"atLeast":0,"lessThan":12075,"subtract":0,"rate":0,"baseTax":0},
          {"atLeast":12075,"lessThan":20925,"subtract":12075,"rate":0.10,"baseTax":0},
          {"atLeast":20925,"lessThan":45800,"subtract":20925,"rate":0.12,"baseTax":885},
          {"atLeast":45800,"lessThan":64925,"subtract":45800,"rate":0.22,"baseTax":3870},
          {"atLeast":64925,"lessThan":112950,"subtract":64925,"rate":0.24,"baseTax":8077.50},
          {"atLeast":112950,"lessThan":140175,"subtract":112950,"rate":0.32,"baseTax":19603.50},
          {"atLeast":140175,"lessThan":332375,"subtract":140175,"rate":0.35,"baseTax":28315.50},
          {"atLeast":332375,"lessThan":null,"subtract":332375,"rate":0.37,"baseTax":95585.50}
        ]
      }
    },
    "step4bAdjustmentWhenStep2Unchecked": { "married": 12900, "single": 8600, "hoh": 8600, "mfj": 12900, "mfs": 8600 }
  },
  "mn": {
    "standardDeduction": { "single": 15300, "married": 30600, "mfj": 30600, "mfs": 15300, "hoh": 23000 },
    "allowanceValue": 5300,
    "supplementalRate": 0.0625,
    "paidLeaveWageBase": 184500,
    "paidLeaveEmployeeRate": 0.0044,
    "paidLeaveEmployerStandardRate": 0.0044,
    "paidLeaveEmployerSmallRate": 0.0022,
    "uiWageBase": 44000,
    "uiBaseTaxRate": 0.004,
    "uiAdditionalAssessmentRate": 0.14,
    "uiFederalLoanInterestAssessmentRate": 0,
    "uiWorkforceDevelopmentFeeRate": 0.001,
    "uiDefaultRate": 0.004,
    "brackets": {
      "single":  [[0,33310,0.0535],[33310,109430,0.068],[109430,203150,0.0785],[203150,null,0.0985]],
      "married": [[0,48700,0.0535],[48700,193480,0.068],[193480,337930,0.0785],[337930,null,0.0985]],
      "mfj":     [[0,48700,0.0535],[48700,193480,0.068],[193480,337930,0.0785],[337930,null,0.0985]],
      "mfs":     [[0,24350,0.0535],[24350,96740,0.068],[96740,168965,0.0785],[168965,null,0.0985]],
      "hoh":     [[0,41010,0.0535],[41010,164800,0.068],[164800,270060,0.0785],[270060,null,0.0985]]
    }
  },
  "ny": {
    "exemptionBase": { "single": 7400, "married": 7950, "mfj": 7950, "mfs": 7400, "hoh": 7400 },
    "exemptionPerAllowance": 1000,
    "stateSupplementalRate": 0.117,
    "uiWageBase": 17600,
    "uiDefaultRate": 0.09825,
    "uiNewEmployerRate": 0.04025,
    "uiLowestRate": 0.01625,
    "uiHighestRate": 0.09425,
    "rsfRate": 0.00075,
    "pflRate": 0.00432,
    "pflAnnualCap": 411.91,
    "dblWeeklyCap": 0.60,
    "dblRate": 0.005,
    "nysAnnualMethodII": {
      "single": [
        [0,8500,0,0.039,0],[8500,11700,8500,0.044,332],[11700,13900,11700,0.0515,472],
        [13900,80650,13900,0.054,586],[80650,96800,80650,0.059,4190],[96800,107650,96800,0.0703,5143],
        [107650,157650,107650,0.0753,5906],[157650,215400,157650,0.064,9673],[215400,265400,215400,0.1144,13369],
        [265400,1077550,265400,0.0735,19091]
      ],
      "married": [
        [0,8500,0,0.039,0],[8500,11700,8500,0.044,332],[11700,13900,11700,0.0515,472],
        [13900,80650,13900,0.054,586],[80650,96800,80650,0.059,4190],[96800,107650,96800,0.0657,5143],
        [107650,157650,107650,0.0707,5855],[157650,211550,157650,0.0801,9388],[211550,323200,211550,0.064,13708],
        [323200,373200,323200,0.1349,20854],[373200,1077550,373200,0.0735,27600],[1077550,2155350,1077550,0.0765,79369]
      ]
    },
    "nycExemptionBase": { "single": 5000, "married": 5500, "mfj": 5500, "mfs": 5000, "hoh": 5000 },
    "nycExemptionPerAllowance": 1000,
    "nycSupplementalRate": 0.0425,
    "nycAnnualMethodII": {
      "single":  [[0,8000,0,0.0205,0],[8000,8700,8000,0.028,164],[8700,15000,8700,0.0325,184],[15000,25000,15000,0.0395,388],[25000,60000,25000,0.0415,783],[60000,null,60000,0.0425,2236]],
      "married": [[0,8000,0,0.0205,0],[8000,8700,8000,0.028,164],[8700,15000,8700,0.0325,184],[15000,25000,15000,0.0395,388],[25000,60000,25000,0.0415,783],[60000,null,60000,0.0425,2236]]
    },
    "mctmtThreshold": 312500,
    "mctmtRates": {
      "zone1": [[0,375000,0.00055],[375000,437500,0.00115],[437500,2500000,0.006],[2500000,null,0.00895]],
      "zone2": [[0,375000,0.00055],[375000,437500,0.00115],[437500,2500000,0.0034],[2500000,null,0.00635]]
    }
  }
}
```

---

## 5. The one gotcha: `Infinity` is not valid JSON

`CONFIG` uses `Infinity` as the open-ended upper bound in every bracket table
(e.g. `[788000, Infinity, 0.37]`, `lessThan: Infinity`). JSON has no `Infinity`
literal, and `JSON.stringify(Infinity)` produces `null`.

**Rule: store the open upper bound as `null` on the server; the frontend loader
rehydrates `null → Infinity`.** This keeps `progressiveTax()`, `tableTax()`, and
`pub15tScheduleTax()` — all of which compare against the upper bound — working
unchanged.

Do **not** substitute a big sentinel like `9_999_999_999`: `progressiveTax()`
does `upper === Infinity ? Infinity : upper * scaleThresholds`, and a finite
sentinel would be silently scaled by `scaleThresholds`, corrupting the top
bracket. `null → Infinity` is the only safe transform.

Serialization contract, both directions:

| In `CONFIG` (TS) | On the wire (JSON) | After rehydrate (TS) |
|------------------|--------------------|----------------------|
| `Infinity`       | `null`             | `Infinity`           |
| finite number    | same number        | same number          |

---

## 6. API design

Follow the existing REST conventions in [`backend.js`](../helpers/backend.js).
This is reference data (not company-scoped), so a top-level namespace fits better
than `/we`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/payroll/tax-config/current` | The published config for the current calendar year (primary call). |
| `GET` | `/payroll/tax-config/{year}` | A specific year, e.g. `/payroll/tax-config/2026`. |
| `GET` | `/payroll/tax-config` | List available years + metadata (year, status, version, updated_at). |
| `PUT` | `/payroll/tax-config/{year}` | Admin: replace a year's `data` (bumps `version`). |
| `POST` | `/payroll/tax-config/{year}/publish` | Admin: flip `DRAFT → PUBLISHED`. |

**Response envelope** (matches the `{ success, ...response }` pattern the helpers
already expect):

```json
{
  "success": true,
  "year": 2026,
  "version": 3,
  "status": "PUBLISHED",
  "updated_at": "2026-01-02T12:00:00Z",
  "data": { "...": "the §4 document" }
}
```

**DRF sketch** (read endpoint):

```python
# payroll/views.py
from datetime import date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from .models import PayrollTaxConfig

class TaxConfigView(APIView):
    def get(self, request, year=None):
        if year is None:                      # /current
            year = date.today().year
        try:
            cfg = PayrollTaxConfig.objects.get(year=year, status="PUBLISHED")
        except PayrollTaxConfig.DoesNotExist:
            raise NotFound(f"No published tax config for {year}")
        return Response({
            "success": True,
            "year": cfg.year,
            "version": cfg.version,
            "status": cfg.status,
            "updated_at": cfg.updated_at,
            "data": cfg.data,
        })
```

### 6.1 `backend.js` helpers to add

```js
// payroll — tax config (reference data, year-keyed)
export const getCurrentTaxConfig = () => get('/payroll/tax-config/current');
export const getTaxConfig = (year) => get(`/payroll/tax-config/${year}`);
export const listTaxConfigYears = () => get('/payroll/tax-config');
export const putTaxConfig = (year, data) => put(`/payroll/tax-config/${year}`, data);
export const publishTaxConfig = (year) => post(`/payroll/tax-config/${year}/publish`, {});
```

---

## 7. Frontend integration — keep `CONFIG` shape, swap the source

The public function names/signatures in `SalaryProcess.ts` **must not change**
(the header comment lists the callers). So don't thread the config through every
function. Instead, keep a module-level `CONFIG` that starts as the bundled 2026
fallback and gets **replaced** once the backend responds.

### 7.1 Add a loader + rehydrator

```ts
// SalaryProcess.ts — near the top, replacing `const CONFIG = { … }`

const FALLBACK_CONFIG = { /* the current hard-coded 2026 object, unchanged */ };

// `Infinity` <- `null` for every open-ended upper bound.
function reviveInfinity<T>(node: T): T {
  if (Array.isArray(node)) return node.map(reviveInfinity) as unknown as T;
  if (node && typeof node === "object") {
    const out: any = {};
    for (const [k, v] of Object.entries(node as any)) {
      // bracket upper bound and Pub15T `lessThan` are the only open bounds
      out[k] = v === null && (k === "lessThan") ? Infinity : reviveInfinity(v);
    }
    return out;
  }
  return node;
}

// For tuple tables the open bound is positional (index 1 = upper), so also:
function reviveTupleUppers(cfg: any): any {
  const fixRows3or5 = (rows: number[][]) =>
    rows.map((r) => r.map((x, i) => (i === 1 && x === null ? Infinity : x)));
  // apply to every [lower, upper, ...] table
  for (const fs of Object.keys(cfg.federal.brackets)) cfg.federal.brackets[fs] = fixRows3or5(cfg.federal.brackets[fs]);
  for (const fs of Object.keys(cfg.mn.brackets)) cfg.mn.brackets[fs] = fixRows3or5(cfg.mn.brackets[fs]);
  for (const fs of Object.keys(cfg.ny.nysAnnualMethodII)) cfg.ny.nysAnnualMethodII[fs] = fixRows3or5(cfg.ny.nysAnnualMethodII[fs]);
  for (const fs of Object.keys(cfg.ny.nycAnnualMethodII)) cfg.ny.nycAnnualMethodII[fs] = fixRows3or5(cfg.ny.nycAnnualMethodII[fs]);
  for (const z of Object.keys(cfg.ny.mctmtRates)) cfg.ny.mctmtRates[z] = fixRows3or5(cfg.ny.mctmtRates[z]);
  return cfg;
}

// Mutable module state. Starts on the bundled fallback so nothing breaks
// before the fetch resolves (SSR, first paint, offline).
let CONFIG: any = FALLBACK_CONFIG;

/** Call once at app/payroll bootstrap. Idempotent, safe to await repeatedly. */
export async function loadTaxConfig(fetchFn: () => Promise<any>): Promise<void> {
  try {
    const res = await fetchFn();                 // e.g. getCurrentTaxConfig()
    if (res?.success && res?.data) {
      CONFIG = reviveTupleUppers(reviveInfinity(res.data));
    }
  } catch {
    // keep FALLBACK_CONFIG — payroll still runs on the last-shipped tables
  }
}
```

> Because `percentageMethodTables` rows are **objects** with a named `lessThan`
> key, `reviveInfinity` handles them; the **tuple** tables use a positional
> upper bound, handled by `reviveTupleUppers`. Keep both.

### 7.2 Wire the bootstrap

Call `loadTaxConfig(getCurrentTaxConfig)` once where payroll screens mount
(e.g. the `salary_process` page or a payroll context provider), *before* the
first calculation. Cache the result so every route doesn't refetch:

- **React Query / SWR:** `useQuery(['tax-config', year], getCurrentTaxConfig, { staleTime: Infinity })` then feed into `loadTaxConfig`.
- **Plain:** fetch once, keep in a context/provider, and `await` it in the payroll run handler.

`localStorage` is a fine secondary cache (`tax-config-2026`) since the data
changes at most a few times a year — key it by `year` + `version` so a server
edit busts it.

### 7.3 Nothing else changes

Every calculator keeps reading `CONFIG.federal.…`, `CONFIG.ny.…` exactly as
today. The only difference is `CONFIG` is now a `let` that may be replaced once.
The exported constants (`SOCIAL_SECURITY_WAGE_BASE_2026`, `NY_UI_DEFAULT_RATE_2026`,
…) can stay as bundled fallbacks; if any external module imports them, keep them
pointing at `FALLBACK_CONFIG` values or re-export getters — audit imports first.

---

## 8. Versioning, year rollover & effective dating

- **One row per year**, `year` unique. 2027 is a new row, not an edit of 2026.
- **`/current`** resolves by calendar year on the server — no client change needed
  in January when the year turns over, provided 2027 is `PUBLISHED`.
- **Historical correctness:** a payroll *run* should pin the config `year` to the
  **pay date's year**, not "today". When recomputing/auditing an old run, request
  `/payroll/tax-config/{payDateYear}` so old paychecks reproduce with the tables
  that were in force. Store the resolved `version` on the saved payroll for audit.
- **`status` DRAFT/PUBLISHED** lets you stage next year's tables without exposing
  them. `/current` and `/{year}` only return `PUBLISHED`.
- **`version`** increments on every `PUT` for cache-busting and audit.

---

## 9. Alternative: fully normalised schema (only if you need row-level reporting)

If finance ever needs to query/report on individual brackets, normalise instead
of (or alongside) the JSON blob:

```
tax_year(id, year, status, effective_from, effective_to)
tax_scalar(tax_year_id, jurisdiction, key, value)          -- ssRate, futaWageBase, uiDefaultRate, …
tax_filing_amount(tax_year_id, jurisdiction, table_key, filing_status, amount)  -- standardDeduction, exemptionBase, step4b…
tax_bracket(tax_year_id, jurisdiction, table_key, filing_status, seq,
            lower, upper NULL, subtract NULL, rate, add_amount NULL, base_tax NULL)
```

`tax_bracket` is a single wide table that covers all three tuple/object formats
(3-tuple, 5-tuple, Pub15TRow) via nullable columns; `upper IS NULL` = open bound.
A serializer re-assembles rows (ordered by `seq`) back into the §4 JSON so the
API contract and the frontend are **identical** either way. Downside: ~500 rows
per year to seed and a non-trivial assembler. Not recommended unless reporting
demands it.

---

## 10. Validation (before publish)

Enforce on `PUT`/publish so a bad edit can't silently skew withholding:

1. **Bracket monotonicity:** within each table, `row[i].upper === row[i+1].lower`
   (contiguous, ascending); exactly one open (`null`) upper bound, and it's last.
2. **Filing-status completeness:** federal `standardDeduction`, `brackets`,
   `percentageMethodTables.{standard,step2}` all present for the keys the code
   looks up (`single/married/mfj/mfs/hoh` where applicable).
3. **Rate sanity:** all `rate` ∈ [0, 1]; wage bases > 0; `uiLowestRate ≤
   uiDefaultRate ≤` (published max, allowing subsidiary/blended headroom).
4. **Row arity:** 3-tuple tables have length 3, 5-tuple tables length 5, Pub15T
   rows carry all five keys.
5. **Shape lock:** every top-level key the frontend reads exists (validate the
   payload against a JSON Schema generated from §4).

Ship a JSON Schema (`payroll_tax_config.schema.json`) and validate on both ends.

---

## 11. Parity test — prove the swap is a no-op

Before removing the hard-coded tables, guarantee backend-fed `CONFIG` produces
identical paychecks:

1. Snapshot outputs of the key exported functions
   (`pub15tFederalIncomeTax`, `estimate_socialSecurityTax`, NY/MN state helpers,
   `estimate_FutaTax`, …) across a grid of `{filingStatus × frequency × gross}`
   using today's hard-coded `CONFIG`.
2. Serialize `CONFIG` → JSON (Infinity→null), run it back through
   `reviveInfinity`/`reviveTupleUppers`, and re-run the same grid.
3. Assert every result is **bit-identical**. This is the gate for seeding the
   backend with the §4 document and flipping `loadTaxConfig` on.

---

## 12. Rollout checklist

- [ ] Add `PayrollTaxConfig` model + migration (§3).
- [ ] Seed 2026 with the §4 JSON (a data migration or admin import); set
      `status=PUBLISHED`, `source_notes` citing IRS Pub 15-T / NY DOL / MN DOR.
- [ ] Add read/admin endpoints (§6) + JSON Schema validation (§10).
- [ ] Add `backend.js` helpers (§6.1).
- [ ] Add `FALLBACK_CONFIG`, `reviveInfinity`, `reviveTupleUppers`,
      `loadTaxConfig`, and make `CONFIG` a `let` (§7).
- [ ] Bootstrap `loadTaxConfig(getCurrentTaxConfig)` at payroll mount + cache.
- [ ] Run the §11 parity test; only then rely on the backend.
- [ ] Keep `FALLBACK_CONFIG` shipped as the offline/first-paint safety net.

**Net effect:** rates become server data. Adding 2027 is one `PUT` +
`publish` — no frontend deploy — and the calculation code is untouched except
for `CONFIG` changing from `const` to a `let` that can be hydrated once.
