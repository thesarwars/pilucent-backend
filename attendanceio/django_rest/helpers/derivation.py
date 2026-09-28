"""Pure attendance-derivation service.

Single source of truth for turning a *manual input* (an optional status plus
optional check-in/out times) and a *resolved shift* into a deterministic
attendance outcome: status, normalized times, worked hours, lateness and
overtime.

Design rules (mirroring the Manual Attendance algorithm spec):

* **Pure** — no clock reads, no DB access, no exceptions for business cases.
  Same inputs always produce the same output. Hard rejects (auth, future date,
  locked period) belong in the caller; this module only derives + warns.
* **Status/time consistency** — off days (ABSENT/HOLIDAY/WEEKEND/LEAVE) clear
  their times and zero worked/late/ot; presence days require or auto-fill them.
* **Grace-aware lateness**, **break-aware worked hours** (break defaults to
  ``lunch_time + tiffin_time``), **daily** overtime only (weekly >40h OT is a
  payroll concern).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, date as date_cls, time as time_cls
from typing import Optional, List

from attendanceio.choices import AttendanceStatusChoices

# Statuses that represent a non-working day: times are cleared and all counts
# zeroed regardless of any times supplied.
OFF_DAY_STATUSES = {
    AttendanceStatusChoices.ABSENT,
    AttendanceStatusChoices.HOLIDAY,
    AttendanceStatusChoices.WEEKEND,
    AttendanceStatusChoices.LEAVE,
    AttendanceStatusChoices.SPECIAL,
    AttendanceStatusChoices.REMOVED,
    AttendanceStatusChoices.DRAFT,
}

# Statuses that represent an attended day: times are required or auto-filled.
PRESENCE_STATUSES = {
    AttendanceStatusChoices.PRESENT,
    AttendanceStatusChoices.LATE_ARRIVAL,
    AttendanceStatusChoices.HALF_DAY,
    AttendanceStatusChoices.EARLY_DEPARTURE,
}

# Context statuses that a manual presence mark would contradict (-> needs_review).
PROTECTED_CONTEXT_STATUSES = {
    AttendanceStatusChoices.HOLIDAY,
    AttendanceStatusChoices.WEEKEND,
    AttendanceStatusChoices.LEAVE,
}

_REF_DATE = date_cls(2000, 1, 1)


@dataclass
class DerivedAttendance:
    status: str
    check_in: Optional[time_cls]
    check_out: Optional[time_cls]
    worked_hours: float
    late_mins: int
    ot_hours: float
    break_mins: int
    needs_review: bool
    warnings: List[str] = field(default_factory=list)


def _shift_crosses_midnight(shift) -> bool:
    if shift is None:
        return False
    if getattr(shift, "kind", None) == "NIGHT":
        return True
    return shift.out_time < shift.in_time


def _minutes_between(start: time_cls, end: time_cls, crosses_midnight: bool = False) -> int:
    """Whole minutes from ``start`` to ``end`` on the same reference day.

    If ``end`` lands before ``start`` and the span is allowed to cross midnight,
    ``end`` rolls to the next day. Otherwise a non-positive span is returned as
    given (callers clamp where needed).
    """
    start_dt = datetime.combine(_REF_DATE, start)
    end_dt = datetime.combine(_REF_DATE, end)
    if end_dt < start_dt and crosses_midnight:
        end_dt += timedelta(days=1)
    return int((end_dt - start_dt).total_seconds() // 60)


def _add_minutes(base: time_cls, minutes: float) -> time_cls:
    return (datetime.combine(_REF_DATE, base) + timedelta(minutes=minutes)).time()


def _default_break_mins(shift) -> int:
    if shift is None:
        return 0
    return (shift.lunch_time or 0) + (shift.tiffin_time or 0)


def _autofill_times(status, shift):
    """Status -> (check_in, check_out) default map. Needs a shift; returns
    ``(None, None)`` when one isn't available."""
    if shift is None:
        return None, None
    grace = shift.grace_time or 0
    regular = shift.regular_hour or 0
    if status == AttendanceStatusChoices.PRESENT:
        return shift.in_time, shift.out_time
    if status == AttendanceStatusChoices.LATE_ARRIVAL:
        return _add_minutes(shift.in_time, grace + 1), shift.out_time
    if status == AttendanceStatusChoices.HALF_DAY:
        return shift.in_time, _add_minutes(shift.in_time, (regular / 2) * 60)
    if status == AttendanceStatusChoices.EARLY_DEPARTURE:
        return shift.in_time, shift.out_time
    return None, None


def _compute_counts(check_in, check_out, break_mins, shift, crosses_midnight):
    """Return (worked_hours, late_mins, ot_hours, clamp_warning)."""
    warning = None
    gross = _minutes_between(check_in, check_out, crosses_midnight)
    net = gross - break_mins
    if net < 0:
        warning = "Worked time is negative after the break deduction; clamped to 0."
        net = 0
    worked = round(net / 60, 2)

    late_mins = 0
    ot_hours = 0.0
    if shift is not None:
        grace = shift.grace_time or 0
        raw_late = _minutes_between(shift.in_time, check_in)
        late_mins = max(0, raw_late - grace)
        regular = shift.regular_hour or 0
        ot_hours = round(max(0.0, worked - regular), 2)
    return worked, late_mins, ot_hours, warning


def derive_attendance(
    *,
    date,
    status: Optional[str],
    check_in: Optional[time_cls],
    check_out: Optional[time_cls],
    break_mins: Optional[int],
    shift,
    context_status: Optional[str] = None,
) -> DerivedAttendance:
    """Deterministically derive an attendance outcome.

    ``status`` is the explicit manual mark (may be ``None`` to let the engine
    infer it). ``context_status`` is the *expected* day resolved from
    holiday/leave/shift precedence; used to infer an unmarked day and to flag
    ``needs_review`` when a manual presence mark contradicts a holiday/leave.
    """
    warnings: List[str] = []

    # 1. Resolve the effective status.
    effective = status or None
    if effective is None:
        if context_status in OFF_DAY_STATUSES or context_status in PROTECTED_CONTEXT_STATUSES:
            effective = context_status
        elif not check_in:
            effective = AttendanceStatusChoices.ABSENT
        else:
            effective = AttendanceStatusChoices.PRESENT  # refined below

    # 2. Off-day: clear times, zero everything.
    if effective in OFF_DAY_STATUSES:
        return DerivedAttendance(
            status=effective,
            check_in=None,
            check_out=None,
            worked_hours=0.0,
            late_mins=0,
            ot_hours=0.0,
            break_mins=0,
            needs_review=False,
            warnings=warnings,
        )

    # 3. Presence day. Auto-fill any missing times from the status map.
    autofilled = False
    if check_in is None or check_out is None:
        fi, fo = _autofill_times(effective, shift)
        if check_in is None and fi is not None:
            check_in, autofilled = fi, True
        if check_out is None and fo is not None:
            check_out, autofilled = fo, True
    if autofilled:
        warnings.append("Missing times were auto-filled from the shift defaults.")

    # Without usable times we cannot compute a presence day; fall back to ABSENT.
    if check_in is None or check_out is None:
        warnings.append(
            "Presence status without check-in/out and no shift to auto-fill; "
            "recorded as ABSENT."
        )
        return DerivedAttendance(
            status=AttendanceStatusChoices.ABSENT,
            check_in=None,
            check_out=None,
            worked_hours=0.0,
            late_mins=0,
            ot_hours=0.0,
            break_mins=0,
            needs_review=False,
            warnings=warnings,
        )

    crosses_midnight = _shift_crosses_midnight(shift)
    if check_out < check_in and not crosses_midnight:
        warnings.append(
            "Check-out is earlier than check-in; treated as crossing midnight."
        )
        crosses_midnight = True

    resolved_break = _default_break_mins(shift) if break_mins is None else break_mins
    worked, late_mins, ot_hours, clamp_warning = _compute_counts(
        check_in, check_out, resolved_break, shift, crosses_midnight
    )
    if clamp_warning:
        warnings.append(clamp_warning)

    # 4. Refine status from the derived numbers (only when not explicitly pinned
    #    to a specific presence sub-status by the caller).
    if status in (None, AttendanceStatusChoices.PRESENT, AttendanceStatusChoices.LATE_ARRIVAL):
        regular = (shift.regular_hour or 0) if shift else 0
        if regular and worked <= regular / 2:
            effective = AttendanceStatusChoices.HALF_DAY
        elif late_mins > 0:
            effective = AttendanceStatusChoices.LATE_ARRIVAL
        else:
            effective = AttendanceStatusChoices.PRESENT

    # 5. needs_review when a presence mark contradicts an expected holiday/leave.
    needs_review = (
        effective in PRESENCE_STATUSES
        and context_status in PROTECTED_CONTEXT_STATUSES
    )
    if needs_review:
        warnings.append(
            f"Marked {effective} on an expected {context_status} day; needs review."
        )

    return DerivedAttendance(
        status=effective,
        check_in=check_in,
        check_out=check_out,
        worked_hours=worked,
        late_mins=late_mins,
        ot_hours=ot_hours,
        break_mins=resolved_break,
        needs_review=needs_review,
        warnings=warnings,
    )
