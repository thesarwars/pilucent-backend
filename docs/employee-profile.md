# Employee Profile — Backend Implementation Prompt

Build the server side of the Employee Profile module for a Bangladesh payroll and HRIS
product. This document is the contract. Every field name, enum value, threshold and
rule below is taken from the working front end (`Employee Profile BD.dc.html`) and its
shared rule libraries; implement them exactly, because the UI already computes against
these names and any drift shows up as a silently wrong payslip.

The product is bilingual (English / Bangla), operates under the Bangladesh Labour Act
2006 as amended 2026, the Bangladesh Labour Rules 2015, and the Income Tax Act 2023 as
amended by the Finance Act 2026.

---

## 1. Non-negotiable principles

These are not style preferences. Each one exists because its absence produced a real
defect in the prototype.

1. **One rule book.** No statutory constant may be a literal in a module. Every
   threshold, rate, day count, divisor and citation is read from a central rule
   repository keyed by effective date. A module that hardcodes `14000` as the minimum
   wage will not follow a gazette revision.

2. **Effective dating everywhere.** Salary structures, classifications, grades,
   designations, departments, shifts, sections and tax profiles are all
   effective-dated records, never mutable columns. Reading "the structure" means
   "the structure in force on date D". A settlement computed in 2025 must still
   reproduce to the paisa in 2027 on the law that applied to it.

3. **Never merge sub-records across employees.** When loading a profile, every
   sub-record (personal, nominees, statutory, tax profile, investments, payment,
   history) is *replaced*, never merged into whatever was previously loaded. Merging
   is how one employee's father's name, NID, mobile number and bank account appeared
   under another employee's name.

4. **Blank is a truthful state.** A record nobody has filled in returns empty fields
   and reports them as onboarding gaps. Do not seed one employee's data as another's
   default, and do not invent plausible values.

5. **Confidence gates production.** Every statutory constant carries a confidence
   state: `DRAFTED` → `CORROBORATED` → `VERIFIED` → `LIVE`. A value below `VERIFIED`
   may be displayed and may drive a simulation. It may **not** reach a released
   payslip, an issued register or a filed return. The gate throws rather than warns.

6. **Compute, never back-solve.** Income tax is produced by a slab walk that returns
   its own numbered trace. Deriving tax as `gross − net − pf` is the reverse of a tax
   computation and is forbidden on any document.

7. **One predicate per question.** If the roster badge and the profile panel both
   answer "does this block payroll?", they call the same function. Two
   implementations produced one record reporting two different verdicts on one screen.

---

## 2. Core entity: Employee

### 2.1 Identity and personal (`emp`)

| Field | Type | Notes |
|---|---|---|
| `code` | string, unique, immutable | Format `EMP-0142`. Business key; never reassigned. |
| `nameEn` | string, **required** | Prints on the service book. Reject create without it. |
| `nameBn` | string | Absent → risk (Bangla payslips and the leave register fall back to English). |
| `fatherName` | string | Feeds `personal` tab completion. |
| `motherName` | string | |
| `marital` | enum `SINGLE \| MARRIED \| DIVORCED \| WIDOWED` | |
| `spouseName` | string | Required when `marital = MARRIED` (soft). |
| `dob` | date | Drives the senior-citizen taxpayer suggestion at age ≥ 65. |
| `gender` | enum `MALE \| FEMALE \| THIRD_GENDER` | Drives taxpayer-category suggestion. |
| `blood` | enum `'' \| A+ \| A- \| B+ \| B- \| O+ \| O- \| AB+ \| AB-` | `''` = not recorded. |
| `religion` | enum `'' \| ISLAM \| HINDU \| BUDDHIST \| CHRISTIAN \| OTHER` | Used for festival-holiday scheduling. |
| `nid` | string | See validation §4.1. |
| `birthCert`, `passport`, `workPermit` | string | `workPermit` required for `NON_RESIDENT_FOREIGN`. |
| `mobile` | string | See validation §4.2. |
| `email` | string | |
| `presentAddress`, `presentDivision` | string, enum division | |
| `permanentSame` | boolean | When true, permanent mirrors present. |
| `permanentAddress`, `permanentDivision` | string, enum division | |
| `emergencyName`, `emergencyRelation`, `emergencyPhone` | string, enum relation, string | |
| `photo` | blob ref | Absent → risk (ID card, service book). |

`division` enum: `DHAKA · CHATTOGRAM · KHULNA · RAJSHAHI · SYLHET · BARISHAL ·
RANGPUR · MYMENSINGH`.

`relation` enum: `SPOUSE · SON · DAUGHTER · FATHER · MOTHER · BROTHER · SISTER · OTHER`.

### 2.2 Employment

| Field | Type | Notes |
|---|---|---|
| `classification` | enum `WORKER \| NON_WORKER` | **Determined by work performed, not job title** — the 2026 amendment made this designation-blind. Cite s.2(65). Changing it is a gated operation (§6.1). |
| `workerCategory` | enum | `PERMANENT · PROBATIONER · TEMPORARY · CASUAL · BADLI · APPRENTICE · SEASONAL`. Drives notice period. |
| `establishment` | enum | `FACTORY · SHOP · COMMERCIAL_ESTABLISHMENT · INDUSTRIAL_ESTABLISHMENT · ROAD_TRANSPORT · TEA_PLANTATION · NEWSPAPER`. Drives earned-leave ratio and accumulation cap. |
| `employmentType` | enum `FULL_TIME \| PART_TIME \| CONTRACT` | `contractEnd` required when `CONTRACT`. |
| `doj` | date | Date of joining. Drives tenure, gratuity, festival-bonus eligibility, proration. |
| `probationEnd` | date | |
| `confirmation` | date | **A future confirmation date is a hard block** — a record confirmed ahead of time cannot be paid as permanent. |
| `department`, `section`, `designation`, `grade`, `shift`, `location` | enum, effective-dated | Each maintains its own change timeline. |
| `manager` | string / FK | |
| `appointmentLetter` | boolean | Absent → risk. |
| `idCard`, `idCardDate` | boolean, date | |
| `completedPayrollRuns` | int, derived | Read-only; drives the retroactive-change warning. |
| `separatedOn`, `separationType` | date, enum | Presence with settlement outstanding is a **hard block**. |

`grade` enum: `G1…G7`. `shift` enum: `A (08:00–17:00) · B (14:00–23:00) · C (23:00–08:00)`.

### 2.3 Nominees (0..n)

`{ id, name, relation, nid, share }` — `share` is a percentage as decimal string.

**Invariant:** when any nominee exists, `Σ share` must equal `100` within
`0.001` tolerance. Not a hard block on payroll, but a **hard block on any provident
fund or gratuity payout**. Zero nominees is a risk with the same payout consequence.

### 2.4 Statutory benefits (`stat`)

```
pfMember          boolean   -- gated by pfConstituted at company level
pfConstituted     boolean   -- company-level; when false, membership cannot be toggled
pfNumber          string
pfEnrolled        date
pfEmployee        decimal%  -- must be within [pfMinPercent, pfMaxPercent] = [7, 8]
pfEmployer        decimal%  -- matches employee contribution
gratuityEligible  boolean
gratuityBasis     enum BASIC | GROSS
gratuityMethod    enum MONTHLY_PROVISION | FUNDED
gratuityFund      string
insuranceCovered  boolean
insurancePolicy   string
insuranceSum      money
insurer           string
festivalGranted   boolean
festivalReason    string   -- required when granted before eligibility
```

Citations to attach: PF s.264 · gratuity s.2(10) · insurance s.99 · festival bonus
Rules 2015 Rule 111(5) · leave s.117 · overtime s.108.

### 2.5 Tax profile (`taxp`)

```
category           enum  -- see below
disabledChildren   int   -- each adds disabledChildAddition to the threshold
etin               string
psr, psrDate       boolean, date
vehicle            enum NONE | UPTO_2500 | ABOVE_2500
accommodation      boolean
accommodationValue money (monthly)
priorEmployer      boolean
priorName, priorIncome, priorTds
taxBorneByEmployer boolean
```

`category` enum: `GENERAL · FEMALE · SENIOR_CITIZEN_65_PLUS · PERSON_WITH_DISABILITY ·
THIRD_GENDER · WAR_WOUNDED_FREEDOM_FIGHTER · NON_RESIDENT_FOREIGN`.

**Suggestion (never auto-apply):** age ≥ 65 → `SENIOR_CITIZEN_65_PLUS`; else
`gender = FEMALE` → `FEMALE`; else `gender = THIRD_GENDER` → `THIRD_GENDER`; else
`GENERAL`. Surface as a suggestion with a one-click accept; the user owns the final
value because disability and freedom-fighter status are not derivable from gender or
age.

> **Critical defect to avoid.** The tax engine keys thresholds off boolean flags
> (`woman`, `disabled`, `thirdGender`, `age`, `gazettedFreedomFighter`,
> `nonResident`), **not** off the category string. Passing only `category` silently
> assessed every employee on the `GENERAL` threshold, so a woman entitled to
> ৳450,000 was taxed at ৳400,000 and over-withheld all year. Translate the category
> into flags in exactly one place and make every caller use it.

### 2.6 Investments (0..n)

`{ id, instrument, amount, proof }`. `instrument` enum: `DPS ·
LIFE_INSURANCE_PREMIUM · SANCHAYAPATRA · LISTED_SHARES · MUTUAL_FUND ·
RECOGNISED_PROVIDENT_FUND · APPROVED_DONATION · OTHER`.

Rebate qualification requires `proof = true`. Provident fund contributions qualify
**only if the fund is recognised**; premature withdrawal triggers pro-rated clawback.

### 2.7 Payment (`pay`)

```
method        enum BANK_TRANSFER | MFS | CASH
cashReason    string  -- REQUIRED when method = CASH
bank, branch, routing, accountName, accountNumber, accountType
mfsProvider   enum BKASH | NAGAD | ROCKET | UPAY
walletNumber  string  -- REQUIRED and 11-digit when method = MFS
walletType    enum SALARY | PERSONAL
onHold, holdReason, holdApprover, holdSince
```

**Cash wages remain lawful** under the Labour Act; what they cost is the employer's
tax deduction (the salary is disallowed under Income Tax Act 2023 s.55). So:
unexplained cash is a hard block; explained cash is a *risk* carrying the
disallowance warning. Do not block lawful cash payment.

---

## 3. The compliance engine

This is the heart of the module. It returns two lists with different consequences.

### 3.1 Hard blocks — the payroll run cannot include this person

| Condition | Message | Fix route |
|---|---|---|
| No salary structure in force for the period | `No salary structure assigned` | salary tab |
| `confirmation > today` | `Confirmation date is in the future` | employment tab, field `f-confirmation` |
| `separatedOn` set, settlement outstanding | `Separated {date} ({type}) — final settlement outstanding` | salary tab |
| `method = MFS` and wallet invalid | `Mobile wallet number missing` | payment tab, `f-wallet` |
| `method = CASH` and no `cashReason` | `Cash payment reason not recorded` | payment tab, `f-cashreason` |
| No `etin` **and** projected liability > 0 | `No e-TIN with tax to withhold` | tax tab, `f-etin` |

### 3.2 Risks — record incomplete, run proceeds

Paid in cash (with reason) · no bank account on file · appointment letter not issued ·
NID missing or malformed · no nominee on file · nominee shares ≠ 100% · no e-TIN while
liability is nil · prior-employer income not declared (when `doj` is mid-income-year) ·
Bangla name missing · photograph missing · service book not generated.

### 3.3 Rules the engine must obey

- **The e-TIN item is conditional, not absolute.** An e-TIN is a hard stop only once
  there is tax to withhold; below the threshold it is a gap. Implement
  `hasTaxLiability(employee)` as a single predicate that runs threshold →
  employment exemption → slab walk on that employee's own category, read from the
  rule book. Branching on a raw projection made the item vanish whenever the
  projection returned `NaN` — neither `> 0` nor `<= 0`.
- **Every finding carries a fix route**: `{ label, fix, tab, field }`. The client
  navigates to the tab and focuses the field. A finding with no route is a dead end.
- **Roster badge and profile panel share this function.** Do not reimplement.
- **Singular and plural agree**: one helper produces `"1 item"` / `"3 items"`. Two
  call sites produced a pill reading `1 items` beside a summary reading `1 item`.
- Blocks and risks must **not** both be reported as "blocks payroll". Doing so
  flagged all sixteen records and told nobody anything.

### 3.4 Tab completion state

Per tab, return `complete | partial | empty | blocked`. `blocked` wins whenever any
hard block routes to that tab. Otherwise:

- `personal` — complete when NID valid **and** `nameBn` **and** `fatherName`
- `employment` — complete when `appointmentLetter`
- `salary` — `complete` when a structure is assigned, else `empty`
- `tax`, `documents` — `partial` until the profile is genuinely finished
- `statutory`, `payment`, `history` — `complete`

---

## 4. Validation

### 4.1 National ID (NID)
Strip non-digits; valid lengths are **10, 13 or 17**. Any other length is malformed.
Needed for the service book, not for a payroll run — so it is a risk, not a block.

### 4.2 Mobile / wallet number
Strip non-digits; must be exactly **11 digits** and start with **`01`**.

### 4.3 Provident fund percentage
Must fall within `[pfMinPercent, pfMaxPercent]` = `[7, 8]` from the rule book. Reject
`NaN` and out-of-range with the range stated in the message.

### 4.4 Reason text on gated changes
Minimum **10 characters**, trimmed. Surface a live character count that turns from
error colour to neutral at the threshold.

### 4.5 Dates
All dates are `YYYY-MM-DD` strings compared lexically — never via locale parsing.
"Today" comes from a single injectable clock (the fixture `asOfDate` in dev), never
`new Date()` scattered through modules; tests must be able to freeze it.

> A year is a label, not a quantity. Never pass a year through the locale number
> formatter — it renders `2026` as `2,026`. Format month-year from the `YYYY-MM`
> string directly, transliterating digits for Bangla but never grouping them.

---

## 5. Salary structure

### 5.1 Templates

| id | Name | Mode | Rule |
|---|---|---|---|
| `std` | Standard 60/50 | Gross-down | Basic 60% of gross · House rent 50% of basic · Medical 7% · Conveyance 3% |
| `classic` | Classic 1.5 divisor | Gross-down | Basic = gross ÷ 1.5 · House rent 50% of basic |
| `rmg` | RMG grade-based | Basic-up | Basic from the gazetted grade wage · gazetted allowances on top |

Components: `BASIC`, `HRA`, `MED`, `CONV`, optional `DA`. Basic is the **balancing
component** in gross-down mode — compute the others and let basic absorb the residual,
so the parts always sum to gross exactly.

> **Report effective percentages, never template percentages.** The document must say
> `58.6% of gross` if that is what is in force, not `60% of gross` because that is what
> the template says. Back-solve the percentage from the amounts actually on file. The
> prototype asserted template values as fact on a statutory document.

### 5.2 Assignment and revision

- **Assignment** (first structure) defaults `effectiveFrom` to date of joining.
- **Revision** defaults `effectiveFrom` to **the start of the next unprocessed
  period**, not the joining date. Defaulting to `doj` silently offered a nine-year
  backdate.
- A past effective date on an employee who already has a structure requires a
  **stated reason**, and the response must report how many processed periods it
  reopens and the arrears queued. Block the save without a reason.
- A revision **closes** the previous structure; it never overwrites it. The superseded
  record stays queryable forever for any period already paid on it.
- Warn (do not block) when the increment exceeds `incrementWarnPct` = 25%, or when
  basic share falls below `basicShareWarnPct` = 50%.
- Block when basic falls below the gazetted grade floor. Test the floor on the **full
  monthly rate**, not the prorated amount — proration is not underpayment.

### 5.3 Minimum wage floors

The gazette sets **both** a basic floor and a total-wage floor per grade, and a
structure can clear one while failing the other. Check both, with separate messages.
Non-payment carries a fine of Tk 50,000–100,000 and up to a year (s.289(1)).

---

## 6. Gated operations (require reason + effective date + audit)

### 6.1 Classification change (`WORKER` ↔ `NON_WORKER`)
Requires effective date and a reason of ≥ 10 characters. The response states how many
completed payroll runs exist for the employee and flags the change as retroactive when
the effective date is in the past. Writes a `classification` history entry.

### 6.2 Backdated salary revision
See §5.2. Returns the count of reopened periods and the arrears amount, and records
the reason on the structure.

### 6.3 Separation
Records `separatedOn` and `separationType`. Until final settlement runs, the employee
is a hard block on payroll. Separation entitlements by type (2026 Act):

| Type | Entitlement |
|---|---|
| `TERMINATION` | 30 days per year, or gratuity, whichever is higher (s.26(4)) |
| `RETRENCHMENT` | 30 days per year, or gratuity, higher (s.20) |
| `DISCHARGE` | 30 days per year, or gratuity, higher (s.22) |
| `DISMISSAL` | 15 days per year, min 1 year service; nil for theft, fraud, dishonesty, rioting, arson or wilful breach (s.23) — **DISPUTED** |
| `RESIGNATION` | Graduated: 7 days/yr (1–3 yrs), 15 (3–10), 30 or gratuity whichever higher (10+) (s.27(4)) — **DISPUTED** |
| `RETIREMENT` | 30 days per year, or gratuity, higher (s.28); retirement age **60** |
| `DEATH` | 30 days per year, **45 above ten years**, or gratuity, higher (s.19); eligibility 1 year |

Resolve the graduated rate **before** using it — a bare `days` field is undefined for
the graduated cases and silently produces `NaN`.

---

## 7. Statutory computations

### 7.1 Gratuity
```
years   = completed service, day precision, part-year > 6 months rounds UP
days    = years > 10 ? 45 : 30          (rule book: gratuityYearBreakpoint etc.)
base    = gratuityBasis = GROSS ? monthlyGross : basic
amount  = round((base / 30) * days * years)
monthly provision = amount / 12
```
Expose the breakpoint-crossing anniversary so the UI can warn that the provision is
about to rise. Floor-dividing months understated this for exactly the records built to
test it: 6y 6m 20d must count as 7.

### 7.2 Overtime
`multiplier` 2 × ordinary rate, on **basic + DA only** (s.108). Monthly hours divisor
`208`.

### 7.3 Festival bonus
`festivalBonusesPerYear` = 2, eligibility at `festivalBonusServiceMonths` = 12 of
service. Fully taxable — no exemption (Income Tax Act 2023 s.32); a frequent source of
under-withholding in March and September. Early grant requires `festivalReason`.

### 7.4 Leave
Earned leave ratio by establishment: 1 day per **18** worked days (factory, shop,
commercial, industrial, road transport), **22** (tea plantation), **11** (newspaper).
Accumulation cap **40** days (most) / **60** (newspaper). Casual **10**, sick **14**,
festival holidays **13** (raised from 11 by the 2026 amendment). Encashment: max 50% of
balance, once per leave year, divisor 30.

### 7.5 Income tax projection

```
annualSalary      = monthlyGross * 12
bonuses           = classification = WORKER ? basic * festivalBonusesPerYear : 0
perquisites       = perquisiteMonthly * 12
employmentIncome  = annualSalary + bonuses + perquisites
exemption         = min(round(employmentIncome * 1/3), 500000)
taxable           = max(0, employmentIncome - exemption)
threshold         = thresholdFor(category) + disabledChildren * disabledChildAddition
slabTax           = walk slabs over max(0, taxable - threshold)
rebate            = round(min(investments * 0.10, taxable * 0.03, 750000))
afterRebate       = max(0, slabTax - rebate)
minApplies        = taxable > threshold AND afterRebate < minimumTax
liability         = minApplies ? minimumTax : afterRebate
periodDeduction   = max(0, round((liability - ytdDeducted) / remainingPeriods))
```

AY 2026-27 values (all `VERIFIED`, from the rule book — do not inline):

- Thresholds: `GENERAL` 400,000 · `FEMALE` 450,000 · `SENIOR_CITIZEN_65_PLUS` 450,000 ·
  `PERSON_WITH_DISABILITY` 525,000 · `THIRD_GENDER` 525,000 ·
  `WAR_WOUNDED_FREEDOM_FIGHTER` 550,000 · `NON_RESIDENT_FOREIGN` 0 (flat 30%, **slab
  walk bypassed entirely**)
- `disabledChildAddition` 50,000 per disabled child, claimable by **one parent only** —
  the system must prevent both parents claiming
- Employment exemption: lower of ⅓ or 500,000
- Rebate: 3% of taxable / 10% of investment / 750,000 ceiling, lowest of three
- Minimum tax: 5,000 flat nationwide (location bands abolished — do not build them);
  1,000 first-time filer
- Perquisite vehicle, **monthly**, by engine capacity: ≤1500cc 15,000 · 1501–2000cc
  20,000 · 2001–2500cc 30,000 · above 2500cc 50,000. The old two-band 10,000/25,000
  structure is superseded; it undertaxed every company-car employee.
- Perquisite ceiling 2,500,000 per employee per year; the excess is disallowed to the
  employer and stays taxable to the employee
- Employer contribution to a **recognised** PF is exempt (Sixth Sch. Pt 1, para 6)
- Gratuity exemption ceiling 25,000,000 from an approved fund
- Net-wealth surcharge bands 10/20/30/35% — the 10% band also bites on more than one
  motor car or a house over 8,000 sq ft, whatever the wealth

The income year runs **July to June**. Return the numbered slab walk as a trace so the
figure can be argued with.

### 7.6 Withholding deadlines
Deposit within 2 weeks of month end (July–May); **same day** for 30 June. Late deposit
charge 2% per month capped at 24 months (s.143), and the defaulter is an
assessee-in-default personally liable for the tax. Quarterly returns 25 Oct / 25 Jan /
25 Apr / 25 Jul (s.177). Under-deduction disallows the expense plus 50% (s.55).

---

## 8. Change history and audit

Every effective-dated field maintains its own timeline:
`{ field, date, from, to, by, reason }`.

Tracked fields: `classification · designation · grade · department · shift · section ·
salary`.

- Filterable by field; default `ALL`, sorted newest first.
- A field with no entries returns an explicit empty result, not a silent blank.
- The audit record is append-only. Corrections are new entries, never edits.
- Every gated operation writes an entry with its reason.

---

## 9. API surface

```
GET    /employees                      ?q= &filter= &page=
       filter: ALL | WORKER | NON_WORKER | PROBATION | BLOCKED
       returns: code, nameEn, nameBn, designation, department, workerCategory,
                classification, dateOfJoining, grossMonthly, blockerCount, fresh

POST   /employees                      minimal create; nameEn required
GET    /employees/{code}               full profile, all sub-records
PATCH  /employees/{code}/personal
PATCH  /employees/{code}/employment
PATCH  /employees/{code}/statutory
PATCH  /employees/{code}/tax-profile
PATCH  /employees/{code}/payment

GET    /employees/{code}/compliance    { blocks[], risks[], tabStates{} }
GET    /employees/{code}/tax-projection { trace[], liability, periodDeduction, ... }

GET    /employees/{code}/salary        structure in force ?on=YYYY-MM-DD
POST   /employees/{code}/salary        assign first structure
POST   /employees/{code}/salary/revise { effectiveFrom, method, value, reason }
GET    /employees/{code}/salary/history

POST   /employees/{code}/classification { to, effective, reason }   -- gated
POST   /employees/{code}/separation      { type, date, reason }     -- gated

GET    /employees/{code}/nominees
PUT    /employees/{code}/nominees      full replace; validates Σ share = 100
GET    /employees/{code}/investments
PUT    /employees/{code}/investments
GET    /employees/{code}/history       ?field=
GET    /employees/{code}/documents

POST   /employees/{code}/documents/service-book
POST   /employees/{code}/documents/appointment-letter
POST   /employees/{code}/documents/id-card
```

### Response conventions

- Money as integer paisa or a decimal string — never a float.
- Dates as `YYYY-MM-DD` strings.
- Every computed statutory figure carries `{ value, basis, citation, confidence }`.
- Validation errors return field-addressable paths matching the UI's field ids
  (`f-nid`, `f-etin`, `f-wallet`, `f-cashreason`, `f-confirmation`, `f-nominee`,
  `f-appointment`, `f-photo`, `f-prior`, `f-nameBn`, `f-accnum`, `f-pfemp`) so the
  client can focus the offending input.
- A gated operation rejected for a missing reason returns the consequence it would
  have had (periods reopened, arrears amount), not just "reason required".

---

## 10. Rounding, money and i18n

- Rounding happens at **named points only**, documented per computation. Never round
  intermediate values in a chain.
- Amount in words is generated for both English (South Asian: lakh, crore) and Bangla,
  for **any** amount. Hardcoding two amounts left every other figure blank on a legal
  document.
- Bangla numerals are a display transliteration applied after formatting, never a
  separate number path.
- Every user-facing statutory string ships in both languages. The API returns keys plus
  the English default; the client swaps at runtime.

---

## 11. Acceptance tests

1. Open employee A, then employee B: **no field of A's personal data, nominees, tax
   profile, investments, bank account or history appears under B**.
2. A record with no structure reports exactly one hard block; a record with a structure
   below its grade floor reports the floor block with both basic and total floors
   checked on the full monthly rate.
3. A female employee's projection uses the 450,000 threshold, not 400,000.
4. An employee with nil projected liability and no e-TIN reports a **risk**, not a
   block. Raise the gross above the threshold: the same item becomes a block.
5. Cash payment with a reason → risk plus disallowance warning. Cash without a reason
   → block.
6. Nominee shares of 60 + 30 report "do not total 100%" with the actual total stated.
7. Revising salary defaults the effective date forward to the next unprocessed period;
   backdating without a reason is rejected and states the periods it would reopen.
8. A classification change with a 9-character reason is rejected; 10 characters
   succeeds and writes one history entry.
9. Service of 6y 6m 20d yields 7 gratuity years, not 6.
10. Every compliance finding navigates to a real tab and focuses a real field.
11. Roster blocker count equals the profile's hard-block count for the same employee.
12. A statutory value below `VERIFIED` throws when a payslip is released, and the error
    names the rule.
13. February (28 days) at full attendance pays a full month — proration factor 1.0, not
    0.9333.
14. Freeze the clock at a known date: every tenure, eligibility and deadline figure is
    reproducible.
