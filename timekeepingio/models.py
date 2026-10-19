"""BD attendance (docs/backend/attendance.md).

Punches are facts; days are derived. A punch row is never updated or
deleted; a wrong day is corrected by an adjustment that overlays the
computation, and removing the adjustment restores the computed value
exactly. Nothing here stores a day's status, worked minutes or overtime as
truth -- `DaySnapshot` is a cache written when a period locks.

Minutes are integers throughout. A shift's times are minutes from midnight;
an end past 1439 crosses midnight (1740 = 05:00 next day).

Tenancy: every table carries `company`, and every read filters on it.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from common.models import BaseModelWithUID

from .choices import (
    AttendanceAuditActionChoices,
    CalendarDayKindChoices,
    CalendarStatusChoices,
    CreditKindChoices,
    DayStatusChoices,
    ExceptionKindChoices,
    ExceptionStateChoices,
    PeriodStatusChoices,
    PunchDirectionChoices,
    PeriodStageChoices,
    PunchSourceChoices,
    QuarantineReasonChoices,
)

APPEND_ONLY = "Attendance history is append-only. Record a correction as a new row."


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(APPEND_ONLY)

    def delete(self):
        raise ValidationError(APPEND_ONLY)


class AppendOnlyModel(BaseModelWithUID):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(APPEND_ONLY)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(APPEND_ONLY)


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


# --------------------------------------------------------------------- shifts


class Shift(BaseModelWithUID):
    """§3.1. A version of a shift from `effective_from`. A shift that has
    been worked is never edited: a change is a new version."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="bd_shifts")
    site = models.ForeignKey("employeeio.Site", on_delete=models.CASCADE, related_name="shifts")
    code = models.CharField(max_length=20)
    label = models.CharField(max_length=120)
    label_bn = _text(120)
    start_min = models.PositiveSmallIntegerField()  # 480 = 08:00
    end_min = models.PositiveSmallIntegerField()  # 1020 = 17:00; >1439 crosses midnight
    standard_minutes = models.PositiveSmallIntegerField()  # the span less the unpaid break
    unpaid_break_minutes = models.PositiveSmallIntegerField(default=60)
    late_grace_minutes = models.PositiveSmallIntegerField(default=10)
    ot_starts_after_min = models.PositiveSmallIntegerField(default=0)
    requires_pre_approval = models.BooleanField(default=True)
    is_night_shift = models.BooleanField(default=False)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ("code", "-effective_from")
        constraints = [
            models.UniqueConstraint(fields=["site", "code", "effective_from"],
                                    name="timekeepingio_shift_code_per_site"),
            models.CheckConstraint(condition=Q(start_min__lte=1439, end_min__lte=2879, end_min__gt=F("start_min")),
                                   name="timekeepingio_shift_minutes_in_day"),
            models.CheckConstraint(
                condition=Q(standard_minutes__lte=F("end_min") - F("start_min") - F("unpaid_break_minutes") + 1),
                name="timekeepingio_shift_standard_le_span",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.start_min}-{self.end_min}"

    @property
    def crosses_midnight(self):
        return self.end_min > 1439


class ShiftAssignment(BaseModelWithUID):
    """§3.2. Which shift an employee is on, effective-dated. Assignments never
    overlap (enforced in services.shifts), so "which shift was she on last
    March" has one answer."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="shift_assignments")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="assignments")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ("employee", "-effective_from")
        constraints = [
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                                   name="timekeepingio_assignment_window_not_inverted"),
        ]


# -------------------------------------------------------------------- punches


class Punch(AppendOnlyModel):
    """§3.3. Immutable: no update, no delete. `raw_payload` is the evidence;
    the parsed columns are an interpretation."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="punches")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, related_name="+")
    punched_at = models.DateTimeField()
    # Not DATE(punched_at): a night shift's 02:07 belongs to the day before.
    business_date = models.DateField()
    direction = models.CharField(max_length=3, choices=PunchDirectionChoices.choices)
    source = models.CharField(max_length=10, choices=PunchSourceChoices.choices)
    device_id = models.CharField(max_length=80, null=True, blank=True)
    device_punch_id = models.CharField(max_length=80, null=True, blank=True)
    raw_payload = models.JSONField(null=True, blank=True)
    ingested_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ("employee", "punched_at")
        indexes = [models.Index(fields=["employee", "business_date"], name="timekeepingio_punch_emp_date")]
        constraints = [
            # The idempotency guarantee: a replayed buffer cannot double-punch.
            models.UniqueConstraint(fields=["device_id", "device_punch_id"],
                                    condition=Q(device_id__isnull=False, device_punch_id__isnull=False),
                                    name="timekeepingio_punch_device_once"),
        ]


class PunchVoid(AppendOnlyModel):
    """A punch that no longer counts -- its import batch was reversed. The
    punch itself is never touched: the void is a second, append-only fact,
    and the register reads punches without one."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    punch = models.OneToOneField(Punch, on_delete=models.PROTECT, related_name="void")
    reason = models.TextField()
    source_ref = models.CharField(max_length=40)  # IMP-0031
    actor = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor_name = _text()


class PunchQuarantine(BaseModelWithUID):
    """§8.3. A punch that cannot be placed is held, counted and surfaced --
    never dropped."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    device_id = models.CharField(max_length=80, null=True, blank=True)
    raw_payload = models.JSONField()
    reason = models.CharField(max_length=20, choices=QuarantineReasonChoices.choices)
    detail = _text()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ("-created_at",)


# ------------------------------------------------------------------- calendar


class HolidayCalendar(BaseModelWithUID):
    """§3.7. A site's year. Computing a day without a PUBLISHED calendar
    refuses rather than assume Friday."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.CASCADE, related_name="holiday_calendars")
    calendar_year = models.PositiveSmallIntegerField()
    # Keyed by ISO weekday ("5" = Friday): 1 a full weekly holiday, 0.5 a half day.
    weekly_pattern = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=CalendarStatusChoices.choices,
                              default=CalendarStatusChoices.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    # The participation committee consulted, per s.118.
    consulted_with = _text()

    class Meta:
        ordering = ("site", "-calendar_year")
        constraints = [
            models.UniqueConstraint(fields=["site", "calendar_year"], name="timekeepingio_calendar_per_site"),
        ]


class HolidayCalendarDay(BaseModelWithUID):
    calendar = models.ForeignKey(HolidayCalendar, on_delete=models.CASCADE, related_name="days")
    holiday_date = models.DateField()
    name = models.CharField(max_length=120)
    name_bn = _text(120)
    kind = models.CharField(max_length=20, choices=CalendarDayKindChoices.choices)

    class Meta:
        ordering = ("holiday_date",)
        constraints = [
            models.UniqueConstraint(fields=["calendar", "holiday_date"], name="timekeepingio_calendar_day_once"),
        ]


# --------------------------------------------------------------------- period


class AttendancePeriod(BaseModelWithUID):
    """§3.4. One month of one site. The labour rule set is pinned when the
    period opens: a rule change mid-month does not alter a month being worked."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.CASCADE, related_name="attendance_periods")
    period_month = models.DateField()  # the first of the month
    status = models.CharField(max_length=10, choices=PeriodStatusChoices.choices, default=PeriodStatusChoices.OPEN)
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    reopen_reason = models.TextField(blank=True, default="")
    # Attendance intake §6: the working stage of an open month, before the lock.
    stage = models.CharField(max_length=10, choices=PeriodStageChoices.choices, default=PeriodStageChoices.OPEN)
    # Locked over unresolved exceptions: why, and how many.
    acknowledge_reason = models.TextField(blank=True, default="")
    exceptions_acknowledged = models.PositiveIntegerField(default=0)
    # The payroll run that consumed the period, and -- after an unlock -- the
    # run it invalidated, so the invalid run can be explained later.
    payroll_run_ref = models.CharField(max_length=40, blank=True, default="")
    payroll_processed_on = models.DateField(null=True, blank=True)
    payroll_invalidated_ref = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        ordering = ("site", "-period_month")
        constraints = [
            models.UniqueConstraint(fields=["site", "period_month"], name="timekeepingio_period_per_site"),
            models.CheckConstraint(condition=Q(reopened_at__isnull=True) | ~Q(reopen_reason=""),
                                   name="timekeepingio_period_reopen_needs_reason"),
        ]


# ---------------------------------------------------------------- adjustments


class Adjustment(BaseModelWithUID):
    """§3.5. The overlay. One live adjustment per employee-day: a second
    correction supersedes the first rather than stacking. A removal is a live
    row with `removed` set, so the history of every correction stays on file
    and the day computes as if there had been none."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="attendance_adjustments")
    business_date = models.DateField()
    period = models.ForeignKey(AttendancePeriod, on_delete=models.PROTECT, related_name="adjustments")
    new_status = models.CharField(max_length=20, choices=DayStatusChoices.choices, blank=True, default="")
    in_time_min = models.PositiveSmallIntegerField(null=True, blank=True)  # regularised in-time
    out_time_min = models.PositiveSmallIntegerField(null=True, blank=True)
    worked_minutes = models.PositiveIntegerField(null=True, blank=True)
    overtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    removed = models.BooleanField(default=False)
    reason = models.TextField()
    note = models.TextField(blank=True, default="")
    actor = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor_name = _text()
    actor_role = _text(120)
    # Live until superseded. The flag carries the one-live rule (a supersede
    # link can only be written after the newer row exists); the link says by what.
    is_live = models.BooleanField(default=True)
    superseded_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="supersedes")

    class Meta:
        ordering = ("employee", "business_date", "-created_at")
        constraints = [
            models.UniqueConstraint(fields=["employee", "business_date"], condition=Q(is_live=True),
                                    name="timekeepingio_adjustment_one_live"),
            models.CheckConstraint(condition=~Q(reason=""), name="timekeepingio_adjustment_reason_present"),
        ]


# ----------------------------------------------------------------- exceptions


class ExceptionDecision(BaseModelWithUID):
    """What a person decided about an exception (§3.6, §5).

    The exception itself is DERIVED -- computeDay raises it from the punches,
    shift and calendar every time -- so storing it would be storing a
    derivation. What is stored is the decision: resolved, or (for a statutory
    breach) acknowledged, by whom and why. One live decision per employee,
    day and kind."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="+")
    business_date = models.DateField()
    period = models.ForeignKey(AttendancePeriod, on_delete=models.PROTECT, related_name="decisions")
    kind = models.CharField(max_length=30, choices=ExceptionKindChoices.choices)
    state = models.CharField(max_length=15, choices=ExceptionStateChoices.choices)
    # e.g. APPROVED / REJECTED for overtime: recorded, never changing what is payable.
    outcome = _text(20)
    resolution = models.TextField(blank=True, default="")
    adjustment = models.ForeignKey(Adjustment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    decided_by_name = _text()
    is_live = models.BooleanField(default=True)
    superseded_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ("employee", "business_date", "kind")
        constraints = [
            models.UniqueConstraint(fields=["employee", "business_date", "kind"],
                                    condition=Q(is_live=True), name="timekeepingio_decision_one_live"),
            # A daily-limit breach is a fact about the employer: never resolved away.
            models.CheckConstraint(condition=~Q(kind="DAILY_LIMIT_EXCEEDED", state="RESOLVED"),
                                   name="timekeepingio_daily_limit_never_resolved"),
        ]


class CompensatoryCredit(BaseModelWithUID):
    """What confirming holiday working earns the worker (s.103, s.118): a
    compensatory day for a weekly holiday; two compensatory days and one
    substitute holiday for a festival holiday. Held here for the leave module."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="+")
    business_date = models.DateField()
    kind = models.CharField(max_length=15, choices=CreditKindChoices.choices)
    days = models.DecimalField(max_digits=4, decimal_places=1)
    decision = models.ForeignKey(ExceptionDecision, on_delete=models.CASCADE, related_name="credits")
    citation = _text()

    class Meta:
        ordering = ("employee", "business_date")


# ------------------------------------------------------------------- snapshot


class DaySnapshot(BaseModelWithUID):
    """§3.8. A cache, written only when a period locks, with the hash of its
    inputs. A read that finds the hash no longer matches recomputes. Never
    truth."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="+")
    business_date = models.DateField()
    period = models.ForeignKey(AttendancePeriod, on_delete=models.CASCADE, related_name="snapshots")
    status = models.CharField(max_length=20, choices=DayStatusChoices.choices)
    worked_minutes = models.PositiveIntegerField()
    overtime_minutes = models.PositiveIntegerField()
    late_minutes = models.PositiveIntegerField()
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    input_hash = models.CharField(max_length=64)
    stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "business_date"], name="timekeepingio_snapshot_once"),
        ]


# ---------------------------------------------------------------------- audit


class AttendanceAudit(AppendOnlyModel):
    """§3.9. Every write, with the rule set and engine version that applied."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    business_date = models.DateField(null=True, blank=True)
    period = models.ForeignKey(AttendancePeriod, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=30, choices=AttendanceAuditActionChoices.choices)
    actor = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor_name = _text()
    actor_role = _text(120)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    engine_version = models.CharField(max_length=40)

    class Meta:
        ordering = ("-created_at",)
        # Role permissions (§11). Lock and reopen are separate permissions:
        # one person closing and reopening a period alone defeats the control.
        permissions = [
            ("write_attendance", "Can adjust attendance and resolve its exceptions"),
            ("acknowledge_attendance", "Can acknowledge a statutory hours breach"),
            ("lock_attendance", "Can lock an attendance period"),
            ("reopen_attendance", "Can reopen a locked attendance period"),
        ]
