# Payroll Tax Config — Frontend Integration

**Goal:** stop shipping the hard-coded `CONFIG` tax tables in `SalaryProcess.ts`.
Fetch them from the backend at payroll time instead, so a new tax year or a new
state is a **server data edit, not a frontend deploy**. The calculators keep
reading a `CONFIG` object — you just swap where it comes from and let it hold
more than federal/NY/MN.

Pairs with the backend spec `PAYROLL_TAX_CONFIG_BACKEND.md`. The backend is built
and live; this document is the frontend half.

---

## 1. What the backend now serves

Base: `/api/v1/we/payroll/tax-config` (same auth/JWT as every other `/we` call).

Statutory tables are stored **one document per `(year, jurisdiction)`** — a
shared `FEDERAL` row plus one row per state. A read names the states you need and
gets back **federal + only those states**, assembled into one `CONFIG`-shaped
object.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/payroll/tax-config/current?states=CA,NY` | Published config for the **current** year: federal + the named states. Primary call. |
| `GET` | `/payroll/tax-config/{year}?states=CA,NY` | Same, for a specific year (use for recomputing/auditing an old run). |
| `GET` | `/payroll/tax-config` | List available `(year, jurisdiction)` rows + metadata (no heavy `data`). |
| `PUT` | `/payroll/tax-config/{year}/{jurisdiction}` | **Staff only.** Upsert one document (bumps `version`). Not for the app. |
| `POST` | `/payroll/tax-config/{year}/{jurisdiction}/publish` | **Staff only.** Flip `DRAFT → PUBLISHED`. |

The app only ever calls the two `GET` read endpoints. `PUT`/`publish` are for an
internal admin/back-office tool, if you build one.

---

## 2. The read response (this is the exact shape)

`GET /payroll/tax-config/current?states=CA,NY`:

```jsonc
{
  "success": true,
  "year": 2026,
  "versions": { "FEDERAL": 3, "NY": 2 },   // per-jurisdiction version (cache key + audit)
  "unavailable": ["CA"],                    // requested but no PUBLISHED row yet
  "data": {
    "year": 2026,
    "federal": { "ssRate": 0.062, "brackets": { … }, "percentageMethodTables": { … }, … },
    "ny":      { "exemptionBase": { … }, "uiWageBase": 17600, "nysAnnualMethodII": { … }, … }
    // note: no "ca" key — CA had no published tables, so it's in `unavailable`
  }
}
```

Key facts:

- **`data` is your `CONFIG`.** Same shape the calculators already read
  (`CONFIG.federal.…`, `CONFIG.ny.…`). Jurisdiction keys are **lowercase**:
  `federal`, `ny`, `mn`, `ca`, …
- **Only requested states come back**, plus federal (always). You never receive
  the other 48 states. Ask for `?states=NY` and you get `{ federal, ny }`.
- **`unavailable`** lists any requested jurisdiction with no published row for
  that year (a state can be payroll-*bookable* on the backend before its rate
  tables exist). Treat it as "cannot compute this state's withholding yet".
- **`versions`** is your cache-bust key and what you pin onto a saved run for
  audit.

The **list** endpoint returns a bare array of `{ uid, year, jurisdiction,
status, version, effective_from, effective_to, source_notes, updated_at }` — use
it to show which years/states exist, not for calculation.

---

## 3. The one serialization gotcha: `null` ⇄ `Infinity`

Every open-ended bracket upper bound is stored as **`null`** on the server (JSON
has no `Infinity`). The calculators compare against `Infinity`, so **rehydrate
`null → Infinity` on the way in.** Two table styles need it:

- **Object rows** (`percentageMethodTables.*`) use a named `lessThan` key → walk
  the tree, `lessThan === null` → `Infinity`.
- **Tuple rows** (`brackets`, `nysAnnualMethodII`, `nycAnnualMethodII`,
  `mctmtRates`) use the **positional** upper bound at index 1 → map each row,
  `row[1] === null` → `Infinity`.

Do **not** substitute a big sentinel number — `progressiveTax()` special-cases
`Infinity` and would scale a finite sentinel, corrupting the top bracket. See
backend spec §5 for the reference `reviveInfinity` / `reviveTupleUppers` helpers;
apply **both**.

---

## 4. What the frontend must actually do

### 4.1 Fetch for the run's states, not "all"

A payroll run has employees across a **set** of states. Compute the **distinct**
work-location states of the employees in the run and request them in one call:

```ts
const states = [...new Set(
  employees.map(e => e.work_locations?.location_state).filter(Boolean)
)];
// e.g. 40 employees across NY/NJ/PA -> "NY,NJ,PA" -> one request
const res = await getTaxConfig(payDateYear, states); // ?states=NY,NJ,PA
```

One request per run (or per year+state-set), **not** per employee.

### 4.2 Load, rehydrate, replace `CONFIG`

Keep `CONFIG` as module state that starts on the bundled fallback and is
**replaced** once the fetch resolves — so function names/signatures don't change
and nothing breaks before the fetch (first paint, SSR, offline).

```ts
let CONFIG: any = FALLBACK_CONFIG;              // the current hard-coded 2026 object

export async function loadTaxConfig(year: number, states: string[]) {
  try {
    const res = await getTaxConfig(year, states);
    if (res?.success && res?.data) {
      CONFIG = reviveTupleUppers(reviveInfinity(res.data));
      return { unavailable: res.unavailable ?? [], versions: res.versions ?? {} };
    }
  } catch { /* keep FALLBACK_CONFIG — payroll still runs on last-shipped tables */ }
  return { unavailable: [], versions: {} };
}
```

Call it once at payroll bootstrap, **before** the first calculation.

### 4.3 Generalize the state calculators from `ny`/`mn` to `CONFIG[state]` — the real work

Today the calculators hardcode `CONFIG.ny.…` and `CONFIG.mn.…`. For all-states
they must look the jurisdiction up **by the employee's state code**:

```ts
const stateCfg = CONFIG[employeeState.toLowerCase()];   // CONFIG["nj"], CONFIG["pa"], …
if (!stateCfg) { /* no tables for this state — see 4.4 */ }
```

This is the substantive change, and it splits into two:

- **Mechanical:** everywhere that reads `CONFIG.ny`/`CONFIG.mn`, read
  `CONFIG[stateKey]` instead. Federal (`CONFIG.federal`) is unchanged.
- **Tax logic per state:** each state's *math* still has to exist. NY uses
  Method II tables + MCTMT; MN uses brackets + paid leave; a new state may use a
  flat rate, its own brackets, or no income tax at all. Serving a state's numbers
  doesn't compute them — a state is only truly supported once its calculator path
  is written **and** its tables are published on the backend. Until then, that
  state comes back in `unavailable`.

> This mirrors the backend: it now *books* payroll journal entries for any state,
> but a state's withholding is only *correct* once both its backend tables and
> its frontend calculator exist. The two rollouts advance state-by-state together.

### 4.4 Handle `unavailable`

If a state your run needs is in `unavailable` (or `CONFIG[state]` is missing),
you cannot compute its state withholding. Don't silently post $0 — surface it:

- Block or warn on the run ("State tax tables for CA aren't available yet"),
  and/or
- Let federal still compute while flagging the affected employees.

Pick per product needs, but make the gap **visible** — a missing table must never
look like "no tax due".

### 4.5 Cache, and pin the year to the pay date

- **Cache** the fetched config keyed by `year` + the `versions` map so a server
  edit busts it. React Query/SWR: `useQuery(['tax-config', year, states.join(',')],
  …, { staleTime: Infinity })`; `localStorage` is a fine secondary cache.
- **Historical correctness:** resolve the year from the **pay date**, not "today".
  When recomputing/auditing an old paycheck, call `/{payDateYear}?states=…` so it
  reproduces with the tables in force then. Store the returned `versions` on the
  saved run.

### 4.6 Keep `FALLBACK_CONFIG`

Ship the current hard-coded 2026 object as `FALLBACK_CONFIG` so payroll still runs
on the last-shipped tables if the fetch fails. It's the offline/first-paint net.

---

## 5. Parity test — prove the swap is a no-op (do this before relying on the API)

Before removing the hard-coded tables, guarantee backend-fed `CONFIG` produces
**bit-identical** paychecks for the states you already support:

1. Snapshot outputs of the key functions (`pub15tFederalIncomeTax`,
   `estimate_socialSecurityTax`, the NY/MN helpers, `estimate_FutaTax`, …) across
   a grid of `{ filingStatus × frequency × gross }` using today's hard-coded `CONFIG`.
2. Fetch federal+NY+MN from the API, run through `reviveInfinity`/`reviveTupleUppers`,
   re-run the same grid.
3. Assert every result matches. Only then flip `loadTaxConfig` on for real runs.

---

## 6. Rollout checklist (frontend)

- [ ] Add `backend.js` helpers: `getCurrentTaxConfig()`, `getTaxConfig(year, states)`,
      `listTaxConfigYears()` (and staff `putTaxConfig`/`publishTaxConfig` if you
      build an admin tool).
- [ ] Add `FALLBACK_CONFIG`, `reviveInfinity`, `reviveTupleUppers`, `loadTaxConfig`;
      make `CONFIG` a `let` that can be replaced once.
- [ ] Compute the run's distinct states and call `loadTaxConfig(payDateYear, states)`
      at payroll bootstrap, before the first calculation.
- [ ] Generalize state calculators from `CONFIG.ny`/`CONFIG.mn` to `CONFIG[state]`.
- [ ] Handle `unavailable` visibly.
- [ ] Cache by `year` + `versions`; pin the year to the pay date; store `versions`
      on saved runs.
- [ ] Run the §5 parity test; keep `FALLBACK_CONFIG` shipped.

**Net:** rates become server data. Adding 2027, or a new state, is a backend
`PUT` + `publish` — no frontend deploy — and the only frontend change per state
is wiring its calculator path (once) to `CONFIG[state]`.

---

## 7. Notes / boundaries

- **What stays on the employee/company, not in this config:** experience-rated
  values (the NY DOL UI rate, MN rate-determination rate) and per-employee W-4
  data live on the tax record and are read by
  `buildFederalW4InputsFromTaxRecord()` / `getTaxExemptions()` as today. The year
  config only supplies the *fallback default* (e.g. `ny.uiDefaultRate`) when the
  record has none. Don't move employer/employee values into the year config.
- **Trust boundary unchanged:** calculation still happens on the frontend; the
  backend books whatever components you send. Moving *rates* server-side is the
  win here — independent server-side verification of withholding would be a later,
  separate effort.
- **Currently published:** `FEDERAL`, `NY`, `MN` for 2026 only. Every other state
  returns via `unavailable` until its tables are published — that's expected, not
  a bug.
