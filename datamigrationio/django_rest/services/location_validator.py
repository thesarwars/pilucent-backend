import logging

from datamigrationio.models import (
    DataMigrationRow,
    DataMigrationValidationIssue,
)
from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationSeverityChoices,
    MigrationIssueTypeChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
    MigrationDuplicateHandlingChoices,
)
from datamigrationio.django_rest.services.field_mapper import FieldMapperService
from datamigrationio.django_rest.services.migration_job_counters import (
    increment_row_status_counter,
)

from wirehouseio.models import Warehouse
from wirehouseio.choicess import WarehouseKindChoices

logger = logging.getLogger(__name__)

VALID_KIND_VALUES = {c.upper() for c in WarehouseKindChoices.values}


class LocationValidatorService:
    @staticmethod
    def validate_job(job, company):
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
            LocationValidatorService._validate_row(row, job, company, mappings, counters)

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
    def _validate_row(row, job, company, mappings, counters):
        mapped_data = FieldMapperService.apply_mapping_to_row(row.raw_data, mappings)
        row.mapped_data = mapped_data
        row.save(update_fields=["mapped_data", "updated_at"])

        issues = []
        row_status = MigrationRowStatusChoices.READY

        title = (mapped_data.get("title") or "").strip()
        short_name = (mapped_data.get("short_name") or "").strip() or None
        full_address = (mapped_data.get("full_address") or "").strip() or None
        kind_raw = (mapped_data.get("kind") or "").strip().upper()
        remark = (mapped_data.get("remark") or "").strip() or None

        # --- Required: title ---
        if not title:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="Location Name is required.",
                    suggested_fix='Provide a value for the "Location Name" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR

        # --- Kind validation ---
        resolved_kind = WarehouseKindChoices.TEMPORARY
        if kind_raw:
            if kind_raw in VALID_KIND_VALUES:
                resolved_kind = kind_raw
            else:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Kind '{kind_raw}' is not valid. "
                            f"Accepted values: MAIN, TEMPORARY. Defaulting to TEMPORARY."
                        ),
                        suggested_fix="Use MAIN or TEMPORARY for the Kind column.",
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Duplicate check ---
        if (
            title
            and job.duplicate_handling == MigrationDuplicateHandlingChoices.SKIP_DUPLICATES
        ):
            existing = Warehouse.objects.filter(
                title__iexact=title, company=company
            ).exclude(status="REMOVED").exists()
            if existing:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.DUPLICATE_LOCATION,
                        severity=MigrationSeverityChoices.DUPLICATE,
                        description=(
                            f"A location named '{title}' already exists in this company."
                        ),
                        suggested_fix="Rename the location or remove the duplicate row.",
                    )
                )
                row_status = MigrationRowStatusChoices.DUPLICATE

        # --- Build normalized_data (store resolved values) ---
        normalized_data = {
            "title": title,
            "short_name": short_name,
            "full_address": full_address,
            "kind": resolved_kind,
            "remark": remark,
        }
        row.normalized_data = normalized_data
        row.status = row_status
        row.save(update_fields=["normalized_data", "status", "updated_at"])

        if issues:
            DataMigrationValidationIssue.objects.bulk_create(issues)

        increment_row_status_counter(counters, row)
