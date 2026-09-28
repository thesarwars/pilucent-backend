from decimal import Decimal

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.models import DataMigrationImpactLine


IMPORTABLE_ROW_STATUSES = [
    MigrationRowStatusChoices.READY,
    MigrationRowStatusChoices.WARNING,
]


def get_row_reference(row):
    data = row.mapped_data or {}
    normalized = row.normalized_data or {}
    reference_fields = [
        "invoice_number",
        "bill_number",
        "expense_number",
        "reference_number",
        "receipt_number",
        "deposit_number",
        "check_number",
        "journal_number",
        "estimate_number",
        "purchase_order_number",
        "transaction_number",
        "external_id",
    ]
    party_fields = [
        "customer",
        "customer_name",
        "vendor",
        "vendor_name",
        "supplier",
        "supplier_name",
        "payee",
        "payee_name",
    ]

    reference = next((str(data.get(field, "")).strip() for field in reference_fields if data.get(field)), "")
    party = next(
        (
            str(data.get(field) or normalized.get(field) or "").strip()
            for field in party_fields
            if data.get(field) or normalized.get(field)
        ),
        "",
    )
    return reference, party


class MigrationDryRunService:
    @staticmethod
    def run(job, company, handler):
        if not handler.import_available:
            return {
                "implemented": False,
                "data_type": job.data_type,
                "message": "Dry run is not available until this migration type has validation and impact support.",
            }

        if job.status not in [
            MigrationStatusChoices.VALIDATED,
            MigrationStatusChoices.IMPACT_REVIEWED,
            MigrationStatusChoices.CONFIRMED,
        ]:
            return {
                "implemented": False,
                "data_type": job.data_type,
                "message": "Validate the migration before running a dry run.",
            }

        if job.error_rows > 0:
            return {
                "implemented": True,
                "can_commit": False,
                "data_type": job.data_type,
                "message": "Dry run blocked because the job still has error rows.",
                "summary": MigrationReconciliationService.build_summary(job),
            }

        if job.status != MigrationStatusChoices.IMPACT_REVIEWED:
            handler.review_impact(job, company)

        summary = MigrationReconciliationService.build_summary(job)
        return {
            "implemented": True,
            "can_commit": summary["checks"]["debits_equal_credits"]["passed"],
            "data_type": job.data_type,
            "message": "Dry run completed. No live records were created.",
            "summary": summary,
        }


class MigrationReconciliationService:
    @staticmethod
    def build_summary(job):
        impact_lines = DataMigrationImpactLine.objects.filter(job=job)
        total_debit = sum((line.debit for line in impact_lines), Decimal("0"))
        total_credit = sum((line.credit for line in impact_lines), Decimal("0"))
        variance = total_debit - total_credit

        return {
            "job_uid": str(job.uid),
            "data_type": job.data_type,
            "status": job.status,
            "row_counts": {
                "total": job.total_rows,
                "ready": job.ready_rows,
                "warnings": job.warning_rows,
                "errors": job.error_rows,
                "duplicates": job.duplicate_rows,
                "skipped": job.skipped_rows,
                "imported": job.imported_rows,
                "failed": job.failed_rows,
            },
            "impact_totals": {
                "debit": str(total_debit),
                "credit": str(total_credit),
                "variance": str(variance),
            },
            "checks": {
                "debits_equal_credits": {
                    "passed": variance == 0,
                    "message": (
                        "Debit and credit preview is balanced."
                        if variance == 0
                        else "Debit and credit preview is not balanced."
                    ),
                },
                "no_blocking_errors": {
                    "passed": job.error_rows == 0,
                    "message": (
                        "No blocking row errors remain."
                        if job.error_rows == 0
                        else "Blocking row errors remain."
                    ),
                },
                "no_failed_imports": {
                    "passed": job.failed_rows == 0,
                    "message": (
                        "No failed imports recorded."
                        if job.failed_rows == 0
                        else "Some rows failed during import."
                    ),
                },
            },
        }


class MigrationRollbackService:
    @staticmethod
    def run(job, user, handler, reason):
        if handler is None or not getattr(handler, "import_available", False):
            return {
                "implemented": False,
                "data_type": job.data_type,
                "message": "Rollback is not implemented for this migration type yet.",
            }

        return handler.rollback(job, user, reason=reason)
