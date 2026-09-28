"""Bulk manual attendance — two-phase (preview -> commit) team marking.

Backs the *Bulk Manual Attendance* page: mark the whole team for one day in a
single pass. ``preview`` is a pure dry-run (per-row outcome + live summary
counts); ``commit`` writes the validated rows transactionally as upserts.

Merge precedence honoured everywhere: **per-row override > batch default >
derived**. Row-level problems are collected, not fatal — a bad employee
reference becomes an error row, the rest of the batch still resolves.
"""

from django.db import transaction
from django.utils import timezone

from rest_framework.serializers import (
    CharField,
    ChoiceField,
    DateField,
    Serializer,
    TimeField,
    UUIDField,
    ValidationError,
)

from attendanceio.choices import AttendanceStatusChoices
from attendanceio.django_rest.helpers.context import resolve_context_for_date
from attendanceio.django_rest.helpers.derivation import derive_attendance
from attendanceio.models import Attendance

from employeeio.choices import EmployeeStatusChoices


# Statuses an admin may set from the bulk page. P / A / L / H / O on the page map
# to PRESENT / ABSENT / LATE_ARRIVAL / HALF_DAY / HOLIDAY; the rest are accepted
# for completeness of manual marking.
MANUAL_STATUS_CHOICES = [
    AttendanceStatusChoices.PRESENT,
    AttendanceStatusChoices.ABSENT,
    AttendanceStatusChoices.LATE_ARRIVAL,
    AttendanceStatusChoices.HALF_DAY,
    AttendanceStatusChoices.HOLIDAY,
    AttendanceStatusChoices.LEAVE,
    AttendanceStatusChoices.WEEKEND,
    AttendanceStatusChoices.EARLY_DEPARTURE,
    AttendanceStatusChoices.SPECIAL,
]

# Status buckets the page's summary strip renders, in display order.
SUMMARY_STATUSES = [
    AttendanceStatusChoices.PRESENT,
    AttendanceStatusChoices.ABSENT,
    AttendanceStatusChoices.LATE_ARRIVAL,
    AttendanceStatusChoices.HALF_DAY,
    AttendanceStatusChoices.HOLIDAY,
    AttendanceStatusChoices.LEAVE,
]


class _BulkDefaultsSerializer(Serializer):
    """Batch-level quick-fill / "mark everyone" values."""

    status = ChoiceField(
        choices=MANUAL_STATUS_CHOICES, required=False, allow_null=True
    )
    check_in = TimeField(required=False, allow_null=True)
    check_out = TimeField(required=False, allow_null=True)
    note = CharField(required=False, allow_blank=True, allow_null=True)


class _BulkRowSerializer(_BulkDefaultsSerializer):
    """Per-employee override row."""

    employee_uid = UUIDField(required=True)


class BulkAttendanceInputSerializer(Serializer):
    date = DateField(required=True)
    defaults = _BulkDefaultsSerializer(required=False)
    rows = _BulkRowSerializer(many=True, required=False)

    def validate_date(self, value):
        if value > timezone.localdate():
            raise ValidationError("Attendance date cannot be in the future.")
        return value

    def validate(self, attrs):
        if not attrs.get("defaults") and not attrs.get("rows"):
            raise ValidationError(
                "Provide 'defaults' (mark everyone) and/or per-employee 'rows'."
            )
        return attrs


def _merge_field(row, defaults, key):
    """Row value wins when the row explicitly carries the key, else the batch
    default, else ``None``."""
    if row is not None and key in row:
        return row[key]
    return defaults.get(key)


def _row_outcome(employee, derived, note, is_explicit):
    return {
        "employee_uid": str(employee.uid),
        "employee_id": employee.employee_id,
        "employee_name": employee.user.name if employee.user_id else None,
        "shift_uid": str(employee.shift.uid) if employee.shift_id else None,
        "status": derived.status,
        "check_in": derived.check_in,
        "check_out": derived.check_out,
        "worked_hours": derived.worked_hours,
        "late_mins": derived.late_mins,
        "ot_hours": derived.ot_hours,
        "break_mins": derived.break_mins,
        "needs_review": derived.needs_review,
        "note": note or None,
        "is_explicit": is_explicit,
        "warnings": derived.warnings,
        "error": None,
    }


def _error_outcome(employee_uid, message):
    return {
        "employee_uid": str(employee_uid),
        "employee_id": None,
        "employee_name": None,
        "shift_uid": None,
        "status": None,
        "check_in": None,
        "check_out": None,
        "worked_hours": 0.0,
        "late_mins": 0,
        "ot_hours": 0.0,
        "break_mins": 0,
        "needs_review": False,
        "note": None,
        "is_explicit": False,
        "warnings": [],
        "error": message,
    }


def _build_summary(outcomes, total):
    counts = {status: 0 for status in SUMMARY_STATUSES}
    marked = 0
    needs_review = 0
    errors = 0
    for outcome in outcomes:
        if outcome["error"]:
            errors += 1
            continue
        status = outcome["status"]
        if status in counts:
            counts[status] += 1
        if outcome["is_explicit"]:
            marked += 1
        if outcome["needs_review"]:
            needs_review += 1
    return {
        "counts": counts,
        "marked": marked,
        "total": total,
        "needs_review": needs_review,
        "errors": errors,
    }


def process_bulk_attendance(*, company, validated, commit):
    """Resolve a bulk request into per-row outcomes + a summary.

    When ``commit`` is true the validated (error-free) rows are written as
    upserts inside a single transaction. Returns ``(outcomes, summary)``.
    """
    date = validated["date"]
    defaults = validated.get("defaults") or {}
    rows = validated.get("rows") or []
    rows_by_uid = {str(row["employee_uid"]): row for row in rows}

    active_employees = (
        company.get_employees()
        .filter(status=EmployeeStatusChoices.ACTIVE)
        .select_related("user", "shift")
    )

    if defaults:
        # "Mark everyone": whole active team, each overridable by its row.
        scope_employees = list(active_employees)
    else:
        # Only the rows the admin actually edited.
        scope_employees = list(
            active_employees.filter(uid__in=list(rows_by_uid.keys()))
        )

    scope_uids = {str(emp.uid) for emp in scope_employees}
    context_map = resolve_context_for_date(scope_employees, date)

    outcomes = []
    writable = []
    for emp in scope_employees:
        row = rows_by_uid.get(str(emp.uid))
        status = _merge_field(row, defaults, "status")
        check_in = _merge_field(row, defaults, "check_in")
        check_out = _merge_field(row, defaults, "check_out")
        note = _merge_field(row, defaults, "note")

        derived = derive_attendance(
            date=date,
            status=status or None,
            check_in=check_in,
            check_out=check_out,
            break_mins=None,
            shift=emp.shift,
            context_status=context_map.get(emp.id),
        )
        outcome = _row_outcome(emp, derived, note, is_explicit=bool(status))
        outcomes.append(outcome)
        writable.append((emp, derived, note))

    # Rows pointing at employees outside the active scope become error rows so
    # the caller sees exactly what was skipped (never silently dropped).
    for uid in rows_by_uid:
        if uid not in scope_uids:
            outcomes.append(
                _error_outcome(uid, "Employee not found or not active in this company.")
            )

    summary = _build_summary(outcomes, total=len(scope_employees))

    if commit and writable:
        with transaction.atomic():
            for emp, derived, note in writable:
                Attendance.objects.update_or_create(
                    employee=emp,
                    date=date,
                    company=company,
                    defaults={
                        "status": derived.status,
                        "check_in": derived.check_in,
                        "check_out": derived.check_out,
                        "worked_hour_count": derived.worked_hours,
                        "shift": emp.shift,
                        "remark": note or None,
                    },
                )

    return outcomes, summary
