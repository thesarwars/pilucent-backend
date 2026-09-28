import logging
import re
from datetime import datetime

from accounts.models import User
from companyio.choices import CompanyDepartmentStatusChoices, CompanyDesignationStatusChoices
from companyio.models import CompanyDepartment, CompanyDesignation
from employeeio.choices import EmploymentTypeChoices, EmployeeStatusChoices

from datamigrationio.choices import (
    MigrationDuplicateHandlingChoices,
    MigrationIssueTypeChoices,
    MigrationRowStatusChoices,
    MigrationSeverityChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)
from datamigrationio.django_rest.services.field_mapper import FieldMapperService
from datamigrationio.django_rest.services.migration_job_counters import (
    increment_row_status_counter,
)
from datamigrationio.models import DataMigrationValidationIssue

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DATE_FORMAT_MAP = {
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYY/MM/DD": "%Y/%m/%d",
    "DD-MM-YYYY": "%d-%m-%Y",
    "MM-DD-YYYY": "%m-%d-%Y",
}

VALID_KIND_VALUES = {c.upper() for c in EmploymentTypeChoices.values}
VALID_STATUS_VALUES = {c.upper() for c in EmployeeStatusChoices.values}
VALID_GENDER_VALUES = {"MALE", "FEMALE", "OTHER"}


def _parse_date(raw, date_format):
    """Return a parsed date string (YYYY-MM-DD) or None on failure."""
    if not raw:
        return None
    fmt = DATE_FORMAT_MAP.get(date_format, "%m/%d/%Y")
    try:
        return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


class EmployeeValidatorService:
    @staticmethod
    def validate_job(job, company) -> dict:
        mappings = list(job.field_mappings.all())
        rows = job.rows.all()

        DataMigrationValidationIssue.objects.filter(job=job, is_resolved=False).delete()

        counters = {
            "ready": 0,
            "warning": 0,
            "error": 0,
            "duplicate": 0,
            "skipped": 0,
        }

        for row in rows:
            EmployeeValidatorService.validate_row(
                row, job, company, mappings, counters=counters, remap_from_raw=True
            )

        job.ready_rows = counters["ready"]
        job.warning_rows = counters["warning"]
        job.error_rows = counters["error"]
        job.duplicate_rows = counters["duplicate"]
        job.skipped_rows = counters["skipped"]
        job.status = MigrationStatusChoices.VALIDATED
        job.current_step = MigrationStepChoices.REVIEW_IMPACT
        job.save(
            update_fields=[
                "ready_rows",
                "warning_rows",
                "error_rows",
                "duplicate_rows",
                "skipped_rows",
                "status",
                "current_step",
                "updated_at",
            ]
        )

        return {
            "job_uid": str(job.uid),
            "total_rows": job.total_rows,
            "ready_rows": counters["ready"],
            "warning_rows": counters["warning"],
            "error_rows": counters["error"],
            "duplicate_rows": counters["duplicate"],
            "skipped_rows": counters["skipped"],
        }

    @staticmethod
    def validate_row(row, job, company, mappings, counters=None, remap_from_raw=True):
        if remap_from_raw:
            mapped_data = FieldMapperService.apply_mapping_to_row(row.raw_data, mappings)
            row.mapped_data = mapped_data
            row.save(update_fields=["mapped_data", "updated_at"])
        else:
            mapped_data = row.mapped_data or {}

        DataMigrationValidationIssue.objects.filter(row=row, is_resolved=False).delete()

        issues = []
        row_status = MigrationRowStatusChoices.READY
        date_format = getattr(job, "date_format", "MM/DD/YYYY") or "MM/DD/YYYY"

        first_name = (mapped_data.get("first_name") or "").strip()
        last_name = (mapped_data.get("last_name") or "").strip()
        email = (mapped_data.get("email") or "").strip()
        phone = (mapped_data.get("phone") or "").strip() or None
        employee_id = (mapped_data.get("employee_id") or "").strip() or None
        code = (mapped_data.get("code") or "").strip() or None
        department_raw = (mapped_data.get("department") or "").strip()
        designation_raw = (mapped_data.get("designation") or "").strip()
        joining_date_raw = (mapped_data.get("joining_date") or "").strip()
        date_of_birth_raw = (mapped_data.get("date_of_birth") or "").strip()
        employment_type_raw = (mapped_data.get("employment_type") or "").strip().upper()
        status_raw = (mapped_data.get("status") or "").strip().upper()
        gender_raw = (mapped_data.get("gender") or "").strip().upper()
        ssn = (mapped_data.get("ssn") or "").strip() or None
        country = (mapped_data.get("country") or "").strip()[:2].lower() or None

        # --- Required: first_name ---
        if not first_name:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="First Name is required.",
                    suggested_fix='Provide a value for the "First Name" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR

        # --- Required: last_name ---
        if not last_name:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="Last Name is required.",
                    suggested_fix='Provide a value for the "Last Name" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR

        # --- Required: email ---
        if not email:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="Email is required.",
                    suggested_fix='Provide a value for the "Email" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR
        elif not EMAIL_RE.match(email):
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description=f"Email '{email}' is not a valid email address.",
                    suggested_fix="Provide a valid email address in the Email column.",
                )
            )
            row_status = MigrationRowStatusChoices.ERROR

        # --- Duplicate check ---
        if (
            email
            and EMAIL_RE.match(email)
            and job.duplicate_handling == MigrationDuplicateHandlingChoices.SKIP_DUPLICATES
        ):
            if User.objects.filter(email__iexact=email).exists():
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.DUPLICATE_EMPLOYEE,
                        severity=MigrationSeverityChoices.DUPLICATE,
                        description=(
                            f"An employee with email '{email}' already exists in the system."
                        ),
                        suggested_fix="Remove the duplicate row or use a different email address.",
                    )
                )
                row_status = MigrationRowStatusChoices.DUPLICATE

        # --- Department lookup (optional, WARNING) ---
        department_id = None
        department_uid = None
        if department_raw:
            dept_obj = CompanyDepartment.objects.filter(
                title__iexact=department_raw,
                company=company,
                status=CompanyDepartmentStatusChoices.ACTIVE,
            ).first()
            if dept_obj:
                department_id = dept_obj.id
                department_uid = str(dept_obj.uid)
            else:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Department '{department_raw}' was not found in this company. "
                            "The employee will be imported without a department."
                        ),
                        suggested_fix=(
                            "Create the department first or leave the Department column blank."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Designation lookup (optional, WARNING) ---
        designation_id = None
        designation_uid = None
        if designation_raw:
            desig_obj = CompanyDesignation.objects.filter(
                title__iexact=designation_raw,
                company=company,
                status=CompanyDesignationStatusChoices.ACTIVE,
            ).first()
            if desig_obj:
                designation_id = desig_obj.id
                designation_uid = str(desig_obj.uid)
            else:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Designation '{designation_raw}' was not found in this company. "
                            "The employee will be imported without a designation."
                        ),
                        suggested_fix=(
                            "Create the designation first or leave the Designation column blank."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Employment type validation (optional, WARNING) ---
        resolved_kind = EmploymentTypeChoices.FULL_TIME
        if employment_type_raw:
            if employment_type_raw in VALID_KIND_VALUES:
                resolved_kind = employment_type_raw
            else:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Employment Type '{employment_type_raw}' is not valid. "
                            f"Valid values: {', '.join(sorted(VALID_KIND_VALUES))}. "
                            "Defaulting to FULL_TIME."
                        ),
                        suggested_fix=(
                            "Use a valid employment type such as FULL_TIME, PART_TIME, CONTRACT, etc."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Status validation (optional, WARNING) ---
        resolved_status = EmployeeStatusChoices.DRAFT
        if status_raw:
            normalized_status = re.sub(r"[\s\-]+", "_", status_raw)
            if normalized_status == "INACTIVE":
                normalized_status = "IN_ACTIVE"
            if normalized_status in VALID_STATUS_VALUES:
                resolved_status = normalized_status
            else:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Status '{status_raw}' is not valid. "
                            "Valid values: DRAFT, ACTIVE, IN_ACTIVE. Defaulting to DRAFT."
                        ),
                        suggested_fix="Use DRAFT, ACTIVE, or IN_ACTIVE for the Status column.",
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Gender validation (optional) ---
        resolved_gender = None
        if gender_raw:
            if gender_raw in VALID_GENDER_VALUES:
                resolved_gender = gender_raw
            else:
                resolved_gender = None

        # --- Date validations (optional, WARNING) ---
        joining_date = None
        if joining_date_raw:
            joining_date = _parse_date(joining_date_raw, date_format)
            if joining_date is None:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.INVALID_DATE,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Joining Date '{joining_date_raw}' could not be parsed "
                            f"using format {date_format}. It will be ignored."
                        ),
                        suggested_fix=(
                            f"Ensure the Joining Date is formatted as {date_format}."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        date_of_birth = None
        if date_of_birth_raw:
            date_of_birth = _parse_date(date_of_birth_raw, date_format)
            if date_of_birth is None:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.INVALID_DATE,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Date of Birth '{date_of_birth_raw}' could not be parsed "
                            f"using format {date_format}. It will be ignored."
                        ),
                        suggested_fix=(
                            f"Ensure the Date of Birth is formatted as {date_format}."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Build normalized_data ---
        normalized_data = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "employee_id": employee_id,
            "code": code,
            "department_id": department_id,
            "department_uid": department_uid,
            "designation_id": designation_id,
            "designation_uid": designation_uid,
            "kind": resolved_kind,
            "status": resolved_status,
            "gender": resolved_gender,
            "joining_date": joining_date,
            "date_of_birth": date_of_birth,
            "ssn": ssn,
            "country": country,
        }
        row.normalized_data = normalized_data
        row.status = row_status
        row.save(update_fields=["normalized_data", "status", "updated_at"])

        if issues:
            DataMigrationValidationIssue.objects.bulk_create(issues)

        if counters is not None:
            increment_row_status_counter(counters, row)
