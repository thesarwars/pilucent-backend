"""Reverse a data-migration estimate import end-to-end.

Estimates have NO GL side effects — no JournalEntry rows, no opening_balance
changes, no FIFO inventory deductions. Rolling back an estimate import simply
means deleting the Sale records (CASCADE removes SaleItem + address / currency /
term connectors) and marking the migration rows as ROLLED_BACK.
"""

import logging
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from common.django_rest.helpers.crud_logger import CrudAction
from salesio.models import Sale

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService

logger = logging.getLogger(__name__)


ROLLBACK_ELIGIBLE_JOB_STATUSES = {
    MigrationStatusChoices.COMPLETED,
    MigrationStatusChoices.PARTIALLY_COMPLETED,
    MigrationStatusChoices.PARTIALLY_ROLLED_BACK,
}


class EstimateMigrationRollbackService:
    """Roll back every Sale (estimate) created by an estimate-migration job."""

    @staticmethod
    def run(job, user, reason=""):
        if job.status not in ROLLBACK_ELIGIBLE_JOB_STATUSES:
            return {
                "implemented": True,
                "rolled_back": False,
                "job_uid": str(job.uid),
                "status": job.status,
                "message": (
                    "Rollback is only available for jobs that have completed "
                    f"or partially completed an import. Current status: {job.status}."
                ),
            }

        imported_rows = list(
            job.rows.filter(
                status=MigrationRowStatusChoices.IMPORTED,
                linked_record_uid__isnull=False,
                linked_record_type="sale",
            )
        )

        if not imported_rows:
            return {
                "implemented": True,
                "rolled_back": False,
                "job_uid": str(job.uid),
                "status": job.status,
                "message": "No imported estimate records were found to roll back.",
            }

        sale_uid_to_rows = defaultdict(list)
        for row in imported_rows:
            sale_uid_to_rows[row.linked_record_uid].append(row)

        sales = list(
            Sale.objects.filter(
                uid__in=sale_uid_to_rows.keys(),
                company=job.company,
                is_estimated=True,
            )
        )
        existing_sale_uids = {str(sale.uid) for sale in sales}

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "rollback_started",
                "reason": reason,
                "sales_targeted": len(sale_uid_to_rows),
            },
        )

        reversed_sales = 0
        failed_sales = 0
        errors = []

        for sale in sales:
            sale_uid = str(sale.uid)
            try:
                with transaction.atomic():
                    # Estimates have no GL side effects — just delete the Sale.
                    # CASCADE removes SaleItem, AddressConnector, CurrencyConnector,
                    # TermConnector automatically.
                    sale.delete()

                for row in sale_uid_to_rows.get(sale_uid, []):
                    row.status = MigrationRowStatusChoices.ROLLED_BACK
                    row.linked_record_uid = None
                    row.linked_record_type = None
                    row.message = (f"Rolled back. {reason}" if reason else "Rolled back.")[:500]
                    row.save(update_fields=[
                        "status",
                        "linked_record_uid",
                        "linked_record_type",
                        "message",
                        "updated_at",
                    ])
                reversed_sales += 1
            except Exception as exc:
                logger.exception("Rollback failed for sale %s: %s", sale_uid, exc)
                failed_sales += 1
                errors.append({"sale_uid": sale_uid, "error": str(exc)})
                for row in sale_uid_to_rows.get(sale_uid, []):
                    row.message = f"Rollback failed: {exc}"[:500]
                    row.save(update_fields=["message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {"action": "rollback_sale_failed", "sale_uid": sale_uid, "error": str(exc)},
                )

        # Rows whose Sale no longer exists — treat as already-rolled-back
        for sale_uid, rows in sale_uid_to_rows.items():
            if sale_uid in existing_sale_uids:
                continue
            for row in rows:
                row.status = MigrationRowStatusChoices.ROLLED_BACK
                row.linked_record_uid = None
                row.linked_record_type = None
                row.message = "Linked estimate no longer exists; row marked as rolled back."
                row.save(update_fields=[
                    "status",
                    "linked_record_uid",
                    "linked_record_type",
                    "message",
                    "updated_at",
                ])

        remaining_imported = job.rows.filter(
            status=MigrationRowStatusChoices.IMPORTED
        ).count()
        rolled_back_rows = job.rows.filter(
            status=MigrationRowStatusChoices.ROLLED_BACK
        ).count()

        job.imported_rows = remaining_imported
        job.completed_at = timezone.now()
        if failed_sales == 0 and remaining_imported == 0:
            job.status = MigrationStatusChoices.ROLLED_BACK
        else:
            job.status = MigrationStatusChoices.PARTIALLY_ROLLED_BACK
        job.save(update_fields=[
            "status",
            "imported_rows",
            "completed_at",
            "updated_at",
        ])

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "rollback_completed",
                "reason": reason,
                "reversed_sales": reversed_sales,
                "failed_sales": failed_sales,
                "rolled_back_rows": rolled_back_rows,
            },
        )

        return {
            "implemented": True,
            "rolled_back": reversed_sales > 0,
            "job_uid": str(job.uid),
            "status": job.status,
            "reversed_sales": reversed_sales,
            "failed_sales": failed_sales,
            "rolled_back_rows": rolled_back_rows,
            "errors": errors,
            "reason": reason,
        }
