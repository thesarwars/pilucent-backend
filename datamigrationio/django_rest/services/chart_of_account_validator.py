import logging
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from accounts.choices import ChartOfAccountStatusChoices
from common.django_rest.helpers.chart_of_account_helpers import (
    detail_type_is_under,
    resolve_import_account_kind,
)
from accounts.models import ChartOfAccount

from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices
from categoryio.models import Category

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


class ChartOfAccountValidatorService:
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
            ChartOfAccountValidatorService.validate_row(
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

        title = (mapped_data.get("title") or "").strip()
        code = (mapped_data.get("code") or "").strip()
        account_type_raw = (mapped_data.get("account_type") or "").strip()
        detail_type_raw = (mapped_data.get("detail_type") or "").strip()
        opening_balance_raw = (mapped_data.get("opening_balance") or "").strip()
        currency = (mapped_data.get("currency") or "USD").strip() or "USD"
        description = (mapped_data.get("description") or "").strip() or None
        status_raw = (mapped_data.get("status") or "ACTIVE").strip().upper() or "ACTIVE"

        # --- Required: title ---
        if not title:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="Account Name is required.",
                    suggested_fix='Provide a value for the "Account Name" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR

        # --- Resolve account_type ---
        account_type_obj = None
        account_type_id = None
        if not account_type_raw:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="Account Type is required.",
                    suggested_fix='Provide a value for the "Account Type" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR
        else:
            # Try to find pre-resolved id from normalized_data first (remap_from_raw=False path)
            existing_id = (row.normalized_data or {}).get("account_type_id")
            if not remap_from_raw and existing_id:
                try:
                    account_type_obj = Category.objects.get(id=existing_id)
                    account_type_id = existing_id
                except Category.DoesNotExist:
                    pass

            if account_type_obj is None:
                account_type_obj = Category.objects.filter(
                    kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                    status=CategoryStatusChoices.ACTIVE,
                    title__iexact=account_type_raw,
                ).first()

            if account_type_obj is None:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.ACCOUNT_TYPE_NOT_FOUND,
                        severity=MigrationSeverityChoices.ERROR,
                        description=(
                            f"Account Type '{account_type_raw}' was not found. "
                            "Check the 'Type and Details Type' reference sheet for valid values."
                        ),
                        suggested_fix="Correct the Account Type value or use the row fix endpoint.",
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.ERROR
            elif resolve_import_account_kind(account_type_obj) is None:
                # It resolved to a real category, but not one that names an
                # account kind -- a detail type used in the Account Type column.
                # Left alone this imported an account with a kind outside
                # ChartOfAccountKindChoices, which appears on no statement and
                # raises on the first automatic posting against it. The row was
                # reported READY, so nothing warned the customer at the one
                # moment their whole ledger is being established.
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.ACCOUNT_TYPE_NOT_FOUND,
                        severity=MigrationSeverityChoices.ERROR,
                        description=(
                            f"Account Type '{account_type_raw}' is a detail "
                            "type, not an account type, so it does not "
                            "determine whether this account is an asset, "
                            "liability, equity, income or expense. Use a value "
                            "from the Account Type column of the 'Type and "
                            "Details Type' reference sheet."
                        ),
                        suggested_fix=(
                            "Use the Account Type column of the reference "
                            "sheet, e.g. 'Assets' rather than 'Checking'."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.ERROR
            else:
                account_type_id = account_type_obj.id

        # --- Resolve detail_type ---
        detail_type_obj = None
        detail_type_id = None
        if not detail_type_raw:
            issues.append(
                DataMigrationValidationIssue(
                    job=job,
                    row=row,
                    issue_type=MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    severity=MigrationSeverityChoices.ERROR,
                    description="Detail Type is required.",
                    suggested_fix='Provide a value for the "Detail Type" column.',
                )
            )
            row_status = MigrationRowStatusChoices.ERROR
        else:
            existing_detail_id = (row.normalized_data or {}).get("detail_type_id")
            if not remap_from_raw and existing_detail_id:
                try:
                    detail_type_obj = Category.objects.get(id=existing_detail_id)
                    detail_type_id = existing_detail_id
                except Category.DoesNotExist:
                    pass

            if detail_type_obj is None:
                detail_type_obj = Category.objects.filter(
                    kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                    status=CategoryStatusChoices.ACTIVE,
                    title__iexact=detail_type_raw,
                ).first()

            if detail_type_obj is None:
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.DETAIL_TYPE_NOT_FOUND,
                        severity=MigrationSeverityChoices.ERROR,
                        description=(
                            f"Detail Type '{detail_type_raw}' was not found. "
                            "Check the 'Type and Details Type' reference sheet for valid values."
                        ),
                        suggested_fix="Correct the Detail Type value or use the row fix endpoint.",
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.ERROR
            elif not detail_type_is_under(account_type_obj, detail_type_obj):
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.DETAIL_TYPE_NOT_FOUND,
                        severity=MigrationSeverityChoices.ERROR,
                        description=(
                            f"Detail Type '{detail_type_raw}' does not belong to "
                            f"Account Type '{account_type_raw}'. The pair decides "
                            "where this account appears on the statements, so a "
                            "mismatch files it in the wrong place."
                        ),
                        suggested_fix=(
                            "Pick a Detail Type listed against that Account Type "
                            "in the 'Type and Details Type' sheet."
                        ),
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.ERROR
            else:
                detail_type_id = detail_type_obj.id

        # --- Validate opening_balance ---
        opening_balance = Decimal("0")
        if opening_balance_raw:
            try:
                opening_balance = Decimal(str(opening_balance_raw).replace(",", ""))
            except (InvalidOperation, ValueError):
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.INVALID_AMOUNT,
                        severity=MigrationSeverityChoices.WARNING,
                        description=(
                            f"Opening Balance '{opening_balance_raw}' is not a valid number. "
                            "Defaulting to 0."
                        ),
                        suggested_fix="Provide a valid numeric value for Opening Balance.",
                    )
                )
                if row_status == MigrationRowStatusChoices.READY:
                    row_status = MigrationRowStatusChoices.WARNING

        # --- Duplicate check ---
        if (
            title
            and job.duplicate_handling == MigrationDuplicateHandlingChoices.SKIP_DUPLICATES
        ):
            dup_qs = ChartOfAccount.objects.filter(
                company=company
            ).exclude(status=ChartOfAccountStatusChoices.REMOVED)

            title_or_code = Q(title__iexact=title)
            if code:
                title_or_code |= Q(code=code)

            if dup_qs.filter(title_or_code).exists():
                issues.append(
                    DataMigrationValidationIssue(
                        job=job,
                        row=row,
                        issue_type=MigrationIssueTypeChoices.DUPLICATE_CHART_OF_ACCOUNT,
                        severity=MigrationSeverityChoices.DUPLICATE,
                        description=(
                            f"A chart of account with the same name or code already exists "
                            f"in this company (title='{title}'"
                            + (f", code='{code}'" if code else "")
                            + ")."
                        ),
                        suggested_fix="Rename the account or remove the duplicate row.",
                    )
                )
                row_status = MigrationRowStatusChoices.DUPLICATE

        # --- Build normalized_data ---
        normalized_data = {
            "title": title,
            "code": code,
            "account_type_id": account_type_id,
            "detail_type_id": detail_type_id,
            "opening_balance": str(opening_balance),
            "currency": currency,
            "description": description,
            "status": status_raw,
        }

        row.normalized_data = normalized_data
        row.status = row_status
        row.save(update_fields=["normalized_data", "status", "updated_at"])

        if issues:
            DataMigrationValidationIssue.objects.bulk_create(issues)

        if counters is not None:
            increment_row_status_counter(counters, row)
