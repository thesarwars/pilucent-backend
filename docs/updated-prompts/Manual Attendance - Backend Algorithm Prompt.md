# Manual Attendance — Backend Algorithm & Logic Prompt

A complete, implementation-ready specification for the **manual attendance** subsystem of Balanzify (US SMB payroll).
Covers single + bulk manual entry, validation, status derivation, worked-hours math, conflict resolution against
shifts/holidays/leave, audit trail, and the downstream link into the daily-attendance process and payroll. Database-,
language- and framework-agnostic — express as services, jobs, or stored procedures as you see fit.

---

## 0. Goal

> Let an authorized user record or correct attendance for one employee or the whole team for a given date (or range),
> with the system deriving status, worked hours, lateness, and overtime deterministically; rejecting impossible inputs;
> reconciling against the assigned shift, holiday calendar, and approved leave; and writing an immutable audit trail
> that the payroll engine can trust.

---

## 1. Core entities (logical)

- **Employee**: `id, status(active/inactive), shiftId, holidayCalendarId, employmentType, timezone, payType(salary/hourly)`.
- **Shift**: `id, name, shiftIn, shiftOut, lunchMins, tiffinMins, regularHours, lateGraceMins, crossesMidnight`.
- **HolidayCalendar**: set of `{date, name, weekendDays[]}`.
- **LeaveRequest** (approved): `employeeId, leaveTypeId, fromDate, toDate, halfDay(bool), status`.
- **AttendanceRecord** (the output): `id, employeeId, date, status, checkIn, checkOut, breakMins, workedHours, lateMins, otHours, source(manual/device/import), note, markedBy, markedAt, version, isLocked`.
- **AttendanceAudit**: append-only `{recordId, action, before, after, actorId, at, reason}`.
- **Status enum**: `PRESENT, ABSENT, LATE, HALF_DAY, HOLIDAY, ON_LEAVE, WEEKEND`.

---

## 2. Inputs

Single: `{ employeeId, date, status?, checkIn?, checkOut?, breakMins?, note?, actorId }`.
Bulk: `{ date | {fromDate,toDate}, scope(all|selected[]|department), defaults{status?,checkIn?,checkOut?,note?}, perEmployeeOverrides[], actorId }`.

All times are wall-clock in the **employee's timezone**; persist normalized to UTC with the original local string kept for display.

---

## 3. Validation (reject before write)

1. **Auth**: actor must have `attendance.write` for the employee's company/department.
2. **Employee active** on `date` (between join date and termination/last-worked).
3. **Date sane**: not in the future beyond `today` (configurable grace); not before join date; within an open (un-finalized, un-locked) period.
4. **Locked period guard**: if an AttendanceRecord for `(employeeId,date)` `isLocked` (payroll already run), reject with `423 Locked` unless actor has `attendance.override` — then require a `reason`.
5. **Time coherence** (when status implies presence):
   - `checkIn` and `checkOut` both present; `checkOut > checkIn` (allow `checkOut` next-day only if the shift `crossesMidnight`).
   - `breakMins ≥ 0` and `breakMins < gross span`.
   - Times within a tolerance window of the shift (configurable, e.g. ±6h) else flag `needsReview`.
6. **Status/time consistency**: `ABSENT`/`HOLIDAY`/`WEEKEND`/`ON_LEAVE` ⇒ times must be empty (clear them). `PRESENT`/`LATE`/`HALF_DAY` ⇒ times required (or derive, see §5).
7. **Duplicate**: one record per `(employeeId,date)` — manual entry **upserts** (new `version`, prior state to audit).

---

## 4. Context resolution (per employee per date)

Resolve in this precedence to pre-compute the *expected* day:
1. **Holiday**: if `date ∈ holidayCalendar` (or `weekday ∈ weekendDays`) → expected `HOLIDAY`/`WEEKEND`.
2. **Approved leave**: if an approved LeaveRequest covers `date` → expected `ON_LEAVE` (or `HALF_DAY` if `halfDay`).
3. **Shift**: else expected working day using the employee's assigned Shift (in/out/lunch/tiffin/regularHours/grace).

The manual input may **override** the expected day, but an override that contradicts a holiday/leave must set `needsReview=true` and record the reason (e.g. marking PRESENT on an approved leave day).

---

## 5. Derivation algorithm

Given validated input + resolved shift:

```
deriveStatus(input, shift, ctx):
  if input.status explicitly set and consistent: status = input.status
  else if ctx == HOLIDAY/WEEKEND/ON_LEAVE: status = ctx
  else if no checkIn: status = ABSENT
  else:
     lateMins = max(0, minutesBetween(shift.shiftIn, checkIn) - shift.lateGraceMins)
     status = LATE if lateMins > 0 else PRESENT

workedHours(input, shift):
  grossMins = minutesBetween(checkIn, checkOut)            // handle midnight cross
  breakMins = input.breakMins ?? (shift.lunchMins + shift.tiffinMins)
  netMins   = max(0, grossMins - breakMins)
  worked    = round(netMins / 60, 2)
  if worked <= shift.regularHours/2 and status in {PRESENT,LATE}: status = HALF_DAY
  otHours   = max(0, worked - shift.regularHours)           // daily OT; weekly OT computed in payroll
  return { worked, otHours, breakMins, lateMins }
```

- **Auto-fill defaults**: if status is set without times, fill from a status→time map (PRESENT = shift.shiftIn/shiftOut, LATE = shift.shiftIn+grace+1, HALF_DAY = shift.shiftIn → shift.shiftIn+regularHours/2). Mark `source=manual`, `autofilled=true`.
- **OFF days** (ABSENT/HOLIDAY/WEEKEND/ON_LEAVE): `worked=0, ot=0, late=0`, times null.
- Rounding policy configurable (nearest minute, or 6/15-min rounding for hourly payroll); keep raw + rounded.

---

## 6. Bulk algorithm

```
bulkMark(req):
  employees = resolveScope(req.scope)            // all active / selected / by dept
  dates     = expandRange(req.date or from..to)  // skip none; weekends/holidays still get a row
  results = []
  for emp in employees:
    for d in dates:
      ctx   = resolveContext(emp, d)             // §4
      input = mergeDefaults(req.defaults, req.perEmployeeOverrides[emp.id], ctx)
      try:
        validate(input)                          // §3 — collect, don't abort the batch
        rec = derive(input, emp.shift, ctx)      // §5
        results.push(stage(rec))
      catch e: results.push(error(emp,d,e))
  return preview(results)                         // two-phase: preview then commit
```

- **Two-phase**: `bulkMark` returns a **preview** (counts per status, conflicts, locked rows skipped). A separate **commit** writes only the validated rows in one transaction; partial failures roll back or are reported per-row (configurable).
- **Idempotency**: a `batchId` makes re-submits safe (upsert by `(employeeId,date)`).
- **Quick-fill / Apply-to-selected**: server honors the same merge precedence (per-employee override > batch default > derived).

---

## 7. Conflict & edge rules

- **Marking PRESENT on holiday/leave** → allowed but `needsReview`; if hourly, counts as worked (holiday pay handled by payroll rules), if it overlaps approved leave, optionally auto-cancel that leave day (configurable) and write both audits.
- **Overlapping/duplicate punches** (device + manual) → manual with higher `source` priority wins, but never silently discard: keep both, mark superseded.
- **Midnight-crossing shift**: the record's `date` is the **shift start date**; `checkOut` may be `date+1`.
- **DST**: compute spans on UTC instants, not local clock arithmetic.
- **Negative/zero worked** after breaks → clamp to 0 and flag.
- **Future-dated** beyond grace → reject.
- **Inactive/terminated** on date → reject.

---

## 8. Persistence, versioning, audit

- Every create/update is an **upsert** that bumps `version` and writes an `AttendanceAudit` row (`before`, `after`, `actorId`, `at`, `reason?`).
- Records are **immutable once the period is locked** by payroll; edits then require `override` permission + reason and create a correction record, never an in-place rewrite of locked data.
- Soft-delete only (status `voided` + audit), so history is preserved.

---

## 9. Downstream contract (to daily-process & payroll)

- The **daily attendance process** job recompiles finalized records for a date/range, sums worked/OT/late per employee, and marks the period ready; manual records feed it identically to device punches.
- **Payroll** reads finalized `workedHours`, `otHours` (re-evaluating weekly OT > 40h per FLSA), leave/holiday days, and half-days to compute gross. Manual `needsReview` rows must be resolved before the period can be locked.

---

## 10. API surface (suggested)

```
POST /attendance/manual            -> upsert one (returns derived record + warnings)
POST /attendance/bulk/preview      -> dry-run, returns per-row outcome + summary
POST /attendance/bulk/commit       -> { batchId } transactional write
PATCH /attendance/{id}             -> edit (version++, audit)
POST /attendance/{id}/void         -> soft delete
GET  /attendance?date=&range=&emp= -> list (with status, worked, late, ot, source, needsReview)
```

Each response includes: derived `status`, `workedHours`, `lateMins`, `otHours`, `needsReview`, `warnings[]`, and `audit` pointer.

---

## 11. Non-functional

- **Determinism**: same inputs + same shift/holiday/leave context ⇒ same output (pure derivation; no clock reads inside derive — pass `now` in).
- **Timezone-correct**, DST-safe, leap-safe.
- **Bulk performance**: chunk large scopes; preview must be O(employees×dates) and stream.
- **Permissions** enforced server-side on every path; all writes audited; locked-period protection is non-bypassable without explicit override scope.

---

## 12. Paste-ready prompt

> Implement the **manual attendance** backend for a US SMB payroll system. Provide single and **bulk** manual entry where an
> authorized user records/corrects attendance for an employee (or whole team) on a date or date range. **Validate** before
> write: actor permission, employee active on date, sane non-future date within an open/un-locked period (locked periods need
> an `override` scope + reason), time coherence (`checkOut>checkIn`, midnight-cross only if the shift allows, `0≤break<span`),
> and status/time consistency (ABSENT/HOLIDAY/WEEKEND/ON_LEAVE clear times; PRESENT/LATE/HALF_DAY require or auto-fill them).
> **Resolve context** per employee/date in precedence Holiday/Weekend → approved Leave → assigned Shift, and flag
> `needsReview` when a manual override contradicts a holiday/leave. **Derive** deterministically: `lateMins = max(0,
> inΔ−grace)`, status PRESENT/LATE/HALF_DAY/ABSENT, `workedHours = round((gross−break)/60,2)` with break defaulting to
> lunch+tiffin, daily `otHours = max(0, worked−regularHours)` (weekly >40h OT left to payroll), OFF days zeroed. **Bulk** is
> two-phase (preview → transactional commit) with `batchId` idempotency, per-row error collection, and merge precedence
> per-employee-override > batch-default > derived. **Persist** as versioned upserts with an append-only audit (before/after,
> actor, time, reason), soft-delete (void), and immutability once payroll locks the period (corrections via override only).
> Expose `/attendance/manual`, `/attendance/bulk/preview`, `/attendance/bulk/commit`, `PATCH /attendance/{id}`,
> `/attendance/{id}/void`, and a list endpoint; every response returns derived status, workedHours, lateMins, otHours,
> needsReview, warnings, and an audit pointer. Keep derivation pure (pass `now` in), timezone/DST-safe, permission-checked on
> every path, and feed finalized records identically to device punches into the daily-process and payroll engines.
