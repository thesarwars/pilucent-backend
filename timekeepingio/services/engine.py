"""computeDay (attendance §6.1): one employee-day from its punches, shift,
calendar kind and any live adjustment. Pure: no I/O, no clock -- today is a
parameter -- so the same inputs always give the same day.

Three positions the computation holds:

- Nothing is capped. Hours above the statutory daily maximum stay in the
  worked and overtime minutes (they are payable); the breach is raised as an
  exception, never clamped away.
- Unapproved overtime is still overtime. OT_UNAPPROVED is raised; the
  minutes do not change.
- No minutes are guessed. An IN with no OUT is MISSING_OUT_PUNCH, not a day
  ending at the shift's end.

Two readings of the spec, stated where they apply: the daily limit compares
worked minutes (which already include overtime) with the maximum; and the
unpaid break is deducted only from a span long enough to require a rest
interval (over 5 hours, s.101), so a 4-hour half day is not 3 hours.
"""

from dataclasses import dataclass, field
from datetime import date

from ..choices import DayStatusChoices as S
from ..choices import ExceptionKindChoices as K

MINUTES_PER_DAY = 1440
# s.101: work over five hours requires a rest interval; below it none is due,
# so none is deducted.
BREAK_DEDUCTED_OVER = 300

WORKING, WEEKLY, HALF, HOLIDAY = "WORKING", "WEEKLY", "HALF", "HOLIDAY"


@dataclass(frozen=True)
class Rules:
    """The statutory figures a day is computed under, from one rule set."""

    rule_set_id: int | None
    version: str
    max_daily_min: int
    standard_daily_min: int
    max_weekly_min: int
    annual_average_weekly_min: int
    overtime_multiplier: int
    standard_month_hours: int
    compensatory_weekly: int
    compensatory_festival: int
    substitute_festival: int
    citations: dict = field(default_factory=dict)
    confidence: str = "DRAFTED"

    @classmethod
    def from_rule_set(cls, rule_set):
        from rulebookio.book import RuleSetView

        L = RuleSetView(rule_set)
        hours = lambda key: int(L.decimal(key) * 60)  # noqa: E731
        cite = lambda key: L.get(key).citation  # noqa: E731
        keys = ("maxDailyHours", "standardHoursPerDay", "maxWeeklyHours", "annualAverageWeeklyHours",
                "overtimeMultiplier", "standardMonthHours", "compensatoryDaysWeeklyHoliday",
                "compensatoryDaysFestivalHoliday", "substituteHolidaysFestival")
        confidences = {L.get(k).confidence for k in keys}
        order = ["DISPUTED", "DRAFTED", "CORROBORATED", "VERIFIED", "LIVE"]
        lowest = min(confidences, key=lambda c: order.index(c) if c in order else 0)
        return cls(
            rule_set_id=rule_set.pk,
            version=rule_set.version,
            max_daily_min=hours("maxDailyHours"),
            standard_daily_min=hours("standardHoursPerDay"),
            max_weekly_min=hours("maxWeeklyHours"),
            annual_average_weekly_min=hours("annualAverageWeeklyHours"),
            overtime_multiplier=int(L.value("overtimeMultiplier")),
            standard_month_hours=int(L.value("standardMonthHours")),
            compensatory_weekly=int(L.value("compensatoryDaysWeeklyHoliday")),
            compensatory_festival=int(L.value("compensatoryDaysFestivalHoliday")),
            substitute_festival=int(L.value("substituteHolidaysFestival")),
            citations={
                "dailyLimit": cite("maxDailyHours"),
                "weeklyLimit": cite("maxWeeklyHours"),
                "annual": f"{cite('annualAverageWeeklyHours')} proviso",
                "overtime": cite("overtimeMultiplier"),
                "compensatory": cite("compensatoryDaysFestivalHoliday"),
                "compensatoryWeekly": cite("compensatoryDaysWeeklyHoliday"),
            },
            confidence=lowest,
        )


# Each exception kind: label, severity, blocks the month closing, the terminal
# state, the remedy (what the action DOES), the action, and the citation key.
EXCEPTIONS = {
    K.MISSING_OUT_PUNCH: ("Missing out-punch", "HIGH", True, "RESOLVED",
                          "Regularise with an out-time, or mark half day", "Regularise", "wages"),
    K.MISSING_IN_PUNCH: ("Missing in-punch", "HIGH", True, "RESOLVED",
                         "Regularise with an in-time, or mark half day", "Regularise", "wages"),
    K.NO_PUNCH_ROSTERED: ("No punches but rostered", "HIGH", True, "RESOLVED",
                          "Mark absent, apply leave, or mark on duty", "Mark absent", "wages"),
    K.ABSENT_NO_LEAVE: ("Absent without leave application", "HIGH", True, "RESOLVED",
                        "Apply leave retrospectively, or mark leave without pay", "Mark LWP", "wages"),
    K.DAILY_LIMIT_EXCEEDED: ("Daily hours above the statutory maximum", "HIGH", True, "ACKNOWLEDGED",
                             "Cannot be resolved away — acknowledge with a reason. The hours are still paid",
                             "Acknowledge", "dailyLimit"),
    K.LATE_ARRIVAL: ("Late beyond grace", "MEDIUM", False, "RESOLVED",
                     "Accept, or regularise with a reason", "Accept", "deduction"),
    K.OT_UNAPPROVED: ("Overtime without pre-approval", "MEDIUM", False, "RESOLVED",
                      "Approve retrospectively. Unapproved overtime is still payable", "Approve", "overtime"),
    K.WORKED_WEEKLY_HOLIDAY: ("Worked on weekly holiday", "MEDIUM", True, "RESOLVED",
                              "Confirm — accrues a compensatory holiday", "Confirm", "compensatoryWeekly"),
    K.WORKED_FESTIVAL_HOLIDAY: ("Worked on festival holiday", "MEDIUM", True, "RESOLVED",
                                "Confirm — accrues 2 compensatory days plus 1 substitute holiday", "Confirm",
                                "compensatory"),
}
FIXED_CITATIONS = {
    "wages": "Bangladesh Labour Act 2006, s.123",
    "deduction": "Bangladesh Labour Act 2006, s.125",
}
HOLIDAY_WORK = (K.WORKED_WEEKLY_HOLIDAY, K.WORKED_FESTIVAL_HOLIDAY)


def citation(kind, rules):
    key = EXCEPTIONS[kind][6]
    return FIXED_CITATIONS.get(key) or rules.citations.get(key) or ""


@dataclass(frozen=True)
class ShiftSpec:
    id: int
    code: str
    label: str
    start_min: int
    end_min: int
    standard_minutes: int
    unpaid_break_minutes: int
    late_grace_minutes: int
    ot_starts_after_min: int
    requires_pre_approval: bool

    @classmethod
    def of(cls, shift):
        return cls(shift.pk, shift.code, shift.label, shift.start_min, shift.end_min, shift.standard_minutes,
                   shift.unpaid_break_minutes, shift.late_grace_minutes, shift.ot_starts_after_min,
                   shift.requires_pre_approval)


@dataclass(frozen=True)
class AdjSpec:
    new_status: str
    in_time_min: int | None
    out_time_min: int | None
    worked_minutes: int | None
    overtime_minutes: int | None


@dataclass
class DayInput:
    day: date
    today: date
    employed: bool
    shift: ShiftSpec | None
    day_kind: str  # WORKING | WEEKLY | HALF | HOLIDAY
    punches: list  # [(minute from the business date's midnight, "IN"/"OUT")], any order
    adjustment: AdjSpec | None = None


@dataclass
class DayRecord:
    day: date
    status: str | None = None
    worked: int = 0
    overtime: int = 0
    late: int = 0
    in_min: int | None = None
    out_min: int | None = None
    exceptions: list = field(default_factory=list)
    adjusted: bool = False
    pending: bool = False
    no_shift: bool = False
    day_kind: str = WORKING
    steps: list = field(default_factory=list)


def hhmm(minute):
    if minute is None:
        return "—"
    day, rest = divmod(minute, MINUTES_PER_DAY)
    text = f"{rest // 60:02d}:{rest % 60:02d}"
    return f"{text} (+1)" if day else text


def _standard(shift, day_kind, rules):
    full = shift.standard_minutes if shift else rules.standard_daily_min
    return full // 2 if day_kind == HALF else full


def _minutes(rec, shift, rules, first_in, last_out):
    """Worked, late and overtime from an in and an out, with the arithmetic."""
    span = last_out - first_in
    deduct = shift.unpaid_break_minutes if span > BREAK_DEDUCTED_OVER else 0
    rec.in_min, rec.out_min = first_in, last_out
    rec.worked = max(0, span - deduct)
    rec.steps.append(f"Span {hhmm(first_in)}–{hhmm(last_out)} = {span} min")
    rec.steps.append(f"Worked = {span} − {deduct} unpaid break = {rec.worked} min"
                     + ("" if deduct else " (no break deducted under 5 hours)"))
    if rec.day_kind in (WORKING, HALF):
        rec.late = max(0, first_in - shift.start_min - shift.late_grace_minutes)
        rec.steps.append(f"Late = max(0, {hhmm(first_in)} − {hhmm(shift.start_min)} − {shift.late_grace_minutes} grace) "
                         f"= {rec.late} min")
    standard = _standard(shift, rec.day_kind, rules)
    rec.overtime = max(0, rec.worked - standard - shift.ot_starts_after_min)
    rec.steps.append(f"Overtime = max(0, {rec.worked} − {standard} standard − {shift.ot_starts_after_min}) "
                     f"= {rec.overtime} min")


def _flag_hours(rec, shift, rules):
    if rec.late > 0:
        rec.exceptions.append(K.LATE_ARRIVAL)
    if rec.overtime > 0 and shift is not None and shift.requires_pre_approval:
        rec.exceptions.append(K.OT_UNAPPROVED)
    if rec.worked > rules.max_daily_min:
        rec.exceptions.append(K.DAILY_LIMIT_EXCEEDED)
        rec.steps.append(f"{rec.worked} min worked > {rules.max_daily_min} statutory daily maximum — breach "
                         "raised, minutes unchanged")
    if rec.worked > 0 and rec.day_kind == WEEKLY:
        rec.exceptions.append(K.WORKED_WEEKLY_HOLIDAY)
    if rec.worked > 0 and rec.day_kind == HOLIDAY:
        rec.exceptions.append(K.WORKED_FESTIVAL_HOLIDAY)


def compute_day(inp: DayInput, rules: Rules) -> DayRecord:
    rec = DayRecord(day=inp.day, day_kind=inp.day_kind)
    if not inp.employed:
        return rec
    adj = inp.adjustment
    if inp.day > inp.today or (inp.day == inp.today and not inp.punches and adj is None):
        rec.pending = True
        return rec
    shift = inp.shift

    # 1. An adjustment that sets the status is the day.
    if adj is not None and adj.new_status:
        rec.adjusted = True
        rec.status = adj.new_status
        standard = _standard(shift, inp.day_kind, rules)
        if adj.in_time_min is not None and adj.out_time_min is not None and shift is not None:
            _minutes(rec, shift, rules, adj.in_time_min, adj.out_time_min)
        else:
            rec.worked = {S.PRESENT: standard, S.ON_DUTY: standard, S.HALF_DAY: standard // 2}.get(adj.new_status, 0)
            rec.steps.append(f"Set to {S(adj.new_status).label.lower()} by an adjustment: {rec.worked} min")
        if adj.worked_minutes is not None:
            rec.worked = adj.worked_minutes
        if adj.overtime_minutes is not None:
            rec.overtime = adj.overtime_minutes
        if adj.new_status == S.ABSENT:
            rec.exceptions.append(K.ABSENT_NO_LEAVE)
        if adj.new_status in (S.PRESENT, S.ON_DUTY, S.HALF_DAY):
            _flag_hours(rec, shift, rules)
            if adj.new_status == S.PRESENT and rec.overtime > 0:
                rec.status = S.PRESENT_OT
        return rec

    # 2. The calendar.
    punches = list(inp.punches)
    if adj is not None and (adj.in_time_min is not None or adj.out_time_min is not None):
        # A regularised time replaces the first IN / last OUT, nothing else.
        rec.adjusted = True
        if adj.in_time_min is not None:
            punches = [p for p in punches if p[1] != "IN"] + [(adj.in_time_min, "IN")]
        if adj.out_time_min is not None:
            punches = [p for p in punches if p[1] != "OUT"] + [(adj.out_time_min, "OUT")]
    if not punches:
        if inp.day_kind == HOLIDAY:
            rec.status = S.HOLIDAY
            return rec
        if inp.day_kind == WEEKLY:
            rec.status = S.WEEKLY_HOLIDAY
            return rec
        if shift is None:
            rec.no_shift = True
            return rec
        # 3. Rostered, nobody punched: say so, do not guess.
        rec.status = S.EXCEPTION
        rec.exceptions.append(K.NO_PUNCH_ROSTERED)
        return rec
    if shift is None:
        rec.no_shift = True
        return rec

    # 4. First IN, last OUT after it.
    ins = sorted(m for m, d in punches if d == "IN")
    if not ins:
        rec.status = S.EXCEPTION
        rec.exceptions.append(K.MISSING_IN_PUNCH)
        rec.out_min = max(m for m, d in punches if d == "OUT")
        return rec
    first_in = ins[0]
    outs = sorted(m for m, d in punches if d == "OUT" and m > first_in)
    if not outs and inp.day >= inp.today:
        # Clocked in today and not yet out: a shift in progress, not a gap.
        rec.pending = True
        rec.in_min = first_in
        return rec
    if not outs:
        rec.status = S.EXCEPTION
        rec.in_min = first_in
        rec.exceptions.append(K.MISSING_OUT_PUNCH)
        return rec
    _minutes(rec, shift, rules, first_in, outs[-1])

    # 5-7. Raise, never adjust.
    _flag_hours(rec, shift, rules)

    # 8.
    rec.status = S.PRESENT_OT if rec.overtime > 0 else S.PRESENT
    return rec


# ------------------------------------------------------------- accrual §6.3

FULL_DAYS = (S.PRESENT, S.PRESENT_OT, S.ON_DUTY)


def days_worked_for_accrual(records, elections):
    """Days that count toward earned leave (s.117) under the company's three
    elections. Never ABSENT or LEAVE_WITHOUT_PAY -- not configurable. Halves
    are kept: 22.5 days, not 22."""
    count = 0.0
    for r in records:
        if r.status in FULL_DAYS:
            count += 1
        elif r.status == S.HALF_DAY:
            count += 0.5
        elif r.status == S.ON_LEAVE and elections.get("paidLeave"):
            count += 1
        elif r.status == S.HOLIDAY and elections.get("festival"):
            count += 1
        elif r.status == S.WEEKLY_HOLIDAY and elections.get("weekly"):
            count += 1
    return count
