"""Attendance intake (docs/backend/attendance-intake-done.md): device profiles,
import batches with the raw file kept, the punches as the device reported
them -- orphans included -- and effective-dated device ID mappings.

Intake is the ingestion layer of the attendance register, not a second
register: a processed punch with an employee is also written to
`timekeepingio.Punch`, which the register computes from, and a reversed
batch's register punches are voided there (`timekeepingio.PunchVoid`). The
period and its lock are the register's own (`timekeepingio.AttendancePeriod`).

Two rules the module exists for (§1):
- a raw punch is never edited or deleted; only its resolution changes, and
  its employee only once, from none;
- an unrecognised device ID never discards a punch: it is held as an orphan
  and attaches the moment a mapping is made.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import BaseModelWithUID

from .choices import (
    BatchStatusChoices,
    DirectionHandlingChoices,
    EncodingChoices,
    FormatChoices,
    IntakeAuditActionChoices,
    MatchingChoices,
    PunchStateChoices,
    RowStructureChoices,
)


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


def _user():
    return models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")


class DeviceProfile(BaseModelWithUID):
    """§3.1. A device's export format, as data. Versioned: a batch keeps the
    version it was parsed under, so a re-parse of its retained file
    reproduces the same punches after the profile is corrected."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.CASCADE, related_name="device_profiles")
    code = models.CharField(max_length=40)
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=160)
    name_bn = _text()
    device_label = models.CharField(max_length=120)  # the mapping key: 'Gazipur main gate'
    device_model = _text(120)  # 'ZKTeco K40' -- shown, never parsed on
    location = _text(120)

    format = models.CharField(max_length=8, choices=FormatChoices.choices, default=FormatChoices.CSV)
    encoding = models.CharField(max_length=14, choices=EncodingChoices.choices, default=EncodingChoices.UTF8)
    delimiter = models.CharField(max_length=4, default=",")
    header_rows = models.PositiveSmallIntegerField(default=1)
    row_structure = models.CharField(max_length=16, choices=RowStructureChoices.choices)
    date_format = models.CharField(max_length=12)
    time_format = models.CharField(max_length=10)
    combined_datetime = models.BooleanField(default=False)
    direction_handling = models.CharField(max_length=16, choices=DirectionHandlingChoices.choices)
    employee_matching = models.CharField(max_length=14, choices=MatchingChoices.choices)
    timezone = models.CharField(max_length=40, default="Asia/Dhaka")
    century_base = models.PositiveSmallIntegerField(default=2000)  # DD-MM-YY: 27 -> 2027
    column_map = models.JSONField()  # [{source, target, start?, width?}]
    pairs = models.JSONField(null=True, blank=True)  # [{in, out}], PAIRED_COLUMNS
    sample_header = _text(500)

    is_active = models.BooleanField(default=True)  # the current version of its code
    created_by = _user()
    created_by_name = _text()

    class Meta:
        ordering = ("site", "code", "-version")
        constraints = [
            models.UniqueConstraint(fields=["company", "code", "version"], name="intakeio_profile_code_version"),
            models.UniqueConstraint(fields=["company", "code"], condition=Q(is_active=True),
                                    name="intakeio_profile_one_active"),
            models.CheckConstraint(condition=Q(header_rows__lte=10), name="intakeio_profile_header_rows_sane"),
        ]

    def __str__(self):
        return f"{self.code} v{self.version}"


class ImportBatch(BaseModelWithUID):
    """§3.2. One uploaded file. The raw bytes are kept: a wrong parse can
    only be redone against the original. Reversal is a state, never a delete."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    reference = models.CharField(max_length=20)  # IMP-0031
    profile = models.ForeignKey(DeviceProfile, on_delete=models.PROTECT, null=True, blank=True, related_name="batches")
    profile_version = models.PositiveIntegerField(null=True, blank=True)
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, related_name="+")

    file = models.FileField(upload_to="attendance/intake", max_length=255)
    file_name = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    file_bytes = models.BigIntegerField()
    file_encoding = _text(14)

    stated_from = models.DateField(null=True, blank=True)
    stated_to = models.DateField(null=True, blank=True)
    parsed_from = models.DateField(null=True, blank=True)
    parsed_to = models.DateField(null=True, blank=True)

    rows_total = models.PositiveIntegerField(default=0)
    rows_parsed = models.PositiveIntegerField(default=0)
    rows_failed = models.PositiveIntegerField(default=0)
    punches_imported = models.PositiveIntegerField(default=0)
    punches_skipped = models.PositiveIntegerField(default=0)
    punches_orphaned = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=10, choices=BatchStatusChoices.choices, default=BatchStatusChoices.UPLOADED)
    parse_json = models.JSONField(null=True, blank=True)  # the summary as shown
    parse_errors_json = models.JSONField(null=True, blank=True)  # [{row, field, value, message}]
    validation_json = models.JSONField(null=True, blank=True)  # the findings as presented
    processed_over = models.JSONField(null=True, blank=True)  # the WARNS findings overridden, and by whom

    uploaded_by = _user()
    uploaded_by_name = _text()
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by_name = _text()
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = _user()
    reversed_by_name = _text()
    reverse_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="intakeio_batch_reference_unique"),
            # The duplicate-upload guard: the same export twice doubles every
            # punch. A reversed batch may be uploaded again after a correction.
            models.UniqueConstraint(fields=["company", "file_sha256"], condition=~Q(status="REVERSED"),
                                    name="intakeio_batch_file_once"),
            models.CheckConstraint(condition=~Q(status="REVERSED") | ~Q(reverse_reason=""),
                                   name="intakeio_batch_reverse_needs_reason"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("An import batch is never deleted: reverse it.")


IMMUTABLE = ("batch_id", "profile_id", "device_label", "device_user_id", "punched_at", "punch_date", "punch_time",
             "source_timezone", "source_row", "raw_row", "direction", "direction_source", "terminal")


class IntakePunchQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("A raw punch cannot be deleted. Reverse the batch.")

    def update(self, **kwargs):
        bad = [k for k in kwargs if k.split("__")[0] in IMMUTABLE or k in ("employee", "employee_id")]
        if bad:
            raise ValidationError(f"A raw punch cannot be edited ({', '.join(bad)}).")
        return super().update(**kwargs)


class IntakePunch(BaseModelWithUID):
    """§3.3. A punch as the device reported it. Only the resolution moves:
    the state, the skip reason, the re-link stamp, the register punch -- and
    the employee, once, from none (the re-link)."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="punches")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="intake_punches")
    profile = models.ForeignKey(DeviceProfile, on_delete=models.PROTECT, related_name="+")
    device_label = models.CharField(max_length=120)
    device_user_id = models.CharField(max_length=60)
    terminal = _text(120)

    punched_at = models.DateTimeField()  # the instant, UTC
    punch_date = models.DateField()  # the Dhaka calendar date
    punch_time = models.TimeField()  # the Dhaka wall time
    source_timezone = models.CharField(max_length=40, default="Asia/Dhaka")
    direction = models.CharField(max_length=3, null=True, blank=True)
    direction_source = models.CharField(max_length=10)  # EXPLICIT | ALTERNATE | FIRST_LAST | PAIRED

    source_row = models.PositiveIntegerField()
    raw_row = models.TextField()

    state = models.CharField(max_length=8, choices=PunchStateChoices.choices, default=PunchStateChoices.ACTIVE)
    skip_reason = _text()
    relinked_at = models.DateTimeField(null=True, blank=True)
    register_punch = models.OneToOneField("timekeepingio.Punch", on_delete=models.PROTECT, null=True, blank=True,
                                          related_name="intake")

    objects = IntakePunchQuerySet.as_manager()

    class Meta:
        ordering = ("punch_date", "punch_time")
        indexes = [
            models.Index(fields=["employee", "punch_date"], name="intakeio_punch_emp_date",
                         condition=Q(state="ACTIVE")),
            models.Index(fields=["company", "device_label", "device_user_id"], name="intakeio_punch_orphan",
                         condition=Q(state="ORPHAN")),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(direction__isnull=True) | Q(direction__in=["IN", "OUT"]),
                                   name="intakeio_punch_direction_known"),
            models.CheckConstraint(condition=~Q(state="ORPHAN") | Q(employee__isnull=True),
                                   name="intakeio_punch_orphan_has_no_employee"),
            models.CheckConstraint(condition=~Q(state="SKIPPED") | ~Q(skip_reason=""),
                                   name="intakeio_punch_skip_has_reason"),
            models.UniqueConstraint(fields=["company", "device_label", "device_user_id", "punched_at"],
                                    condition=Q(state__in=["ACTIVE", "ORPHAN"]), name="intakeio_punch_identity"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            before = type(self).objects.filter(pk=self.pk).values(*IMMUTABLE, "employee_id").first()
            if before is not None:
                moved = [k for k in IMMUTABLE if before[k] != getattr(self, k)]
                if moved:
                    raise ValidationError(f"A raw punch cannot be edited ({', '.join(moved)}). Record an "
                                          "adjustment in the register.")
                if before["employee_id"] is not None and before["employee_id"] != self.employee_id:
                    raise ValidationError("A punch attributed to an employee is never reattributed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("A raw punch cannot be deleted. Reverse the batch.")


class DeviceUserMap(BaseModelWithUID):
    """§3.6. Effective-dated: a device slot given to a new hire closes the
    old mapping, and the old employee keeps their history."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    device_label = models.CharField(max_length=120)
    device_user_id = models.CharField(max_length=60)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.PROTECT, related_name="device_maps")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    relinked_count = models.PositiveIntegerField(default=0)
    created_by = _user()
    created_by_name = _text()
    closed_by_name = _text()

    class Meta:
        ordering = ("device_label", "device_user_id", "-effective_from")
        constraints = [
            models.UniqueConstraint(fields=["company", "device_label", "device_user_id", "effective_from"],
                                    name="intakeio_map_unique"),
            models.UniqueConstraint(fields=["company", "device_label", "device_user_id"],
                                    condition=Q(effective_to__isnull=True), name="intakeio_map_one_open"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gte=models.F(
                "effective_from")), name="intakeio_map_dates"),
        ]


class IntakeEvent(BaseModelWithUID):
    """§10. The outbox: the register and payroll read and mark consumed."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = _text(60)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=["company", "consumed_at"], name="intakeio_event_pending")]


class IntakeAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("The intake audit is append-only.")

    def delete(self):
        raise ValidationError("The intake audit is append-only.")


class IntakeAudit(BaseModelWithUID):
    """§3.8. Append-only."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    action = models.CharField(max_length=24, choices=IntakeAuditActionChoices.choices)
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit")
    period_month = models.DateField(null=True, blank=True)
    site = models.ForeignKey("employeeio.Site", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor = _user()
    actor_name = _text()
    reason = models.TextField(blank=True, default="")
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)

    objects = IntakeAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["site", "period_month", "created_at"], name="intakeio_audit_period")]
        # §8. Lock and unlock are the register's own permissions (lock_attendance,
        # reopen_attendance) -- deliberately separate.
        permissions = [
            ("import_attendance", "Can upload, parse and validate attendance imports"),
            ("process_attendance_import", "Can process an attendance import into the register"),
            ("override_attendance_import", "Can process an attendance import over its warnings"),
            ("reverse_attendance_import", "Can reverse a processed attendance import"),
            ("map_device_users", "Can create and close device ID mappings"),
            ("advance_attendance_period", "Can move an attendance period to processing and review"),
            ("manage_device_profiles", "Can manage attendance device profiles"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("The intake audit is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The intake audit is append-only.")
