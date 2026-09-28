"""Reverse a data-migration purchase order import end-to-end.

Purchase orders have NO GL side effects. Rolling back deletes Purchase records
(CASCADE removes PurchaseItem + address / currency connectors) and marks rows
as ROLLED_BACK.
"""

import logging
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from common.django_rest.helpers.crud_logger import CrudAction
from purchaseio.models import Purchase

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


class PurchaseOrderMigrationRollbackService:
    """Roll back every Purchase created by a purchase-order migration job."""

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
                linked_record_type="purchase",
            )
        )

        if not imported_rows:
            return {
                "implemented": True,
                "rolled_back": False,
                "job_uid": str(job.uid),
                "status": job.status,
                "message": "No imported purchase order records were found to roll back.",
            }

        purchase_uid_to_rows = defaultdict(list)
        for row in imported_rows:
            purchase_uid_to_rows[row.linked_record_uid].append(row)

        purchases = list(
            Purchase.objects.filter(
                uid__in=purchase_uid_to_rows.keys(),
                company=job.company,
                is_bill=False,
                is_cheque=False,
            )
        )
        existing_purchase_uids = {str(purchase.uid) for purchase in purchases}

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "rollback_started",
                "reason": reason,
                "purchases_targeted": len(purchase_uid_to_rows),
            },
        )

        reversed_purchases = 0
        failed_purchases = 0
        errors = []

        for purchase in purchases:
            purchase_uid = str(purchase.uid)
            try:
                with transaction.atomic():
                    purchase.delete()

                for row in purchase_uid_to_rows.get(purchase_uid, []):
                    row.status = MigrationRowStatusChoices.ROLLED_BACK
                    row.linked_record_uid = None
                    row.linked_record_type = None
                    row.message = (
                        f"Rolled back. {reason}" if reason else "Rolled back."
                    )[:500]
                    row.save(
                        update_fields=[
                            "status",
                            "linked_record_uid",
                            "linked_record_type",
                            "message",
                            "updated_at",
                        ]
                    )
                reversed_purchases += 1
            except Exception as exc:
                logger.exception(
                    "Rollback failed for purchase %s: %s", purchase_uid, exc
                )
                failed_purchases += 1
                errors.append({"purchase_uid": purchase_uid, "error": str(exc)})
                for row in purchase_uid_to_rows.get(purchase_uid, []):
                    row.message = f"Rollback failed: {exc}"[:500]
                    row.save(update_fields=["message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "rollback_purchase_failed",
                        "purchase_uid": purchase_uid,
                        "error": str(exc),
                    },
                )

        for purchase_uid, rows in purchase_uid_to_rows.items():
            if purchase_uid in existing_purchase_uids:
                continue
            for row in rows:
                row.status = MigrationRowStatusChoices.ROLLED_BACK
                row.linked_record_uid = None
                row.linked_record_type = None
                row.message = (
                    "Linked purchase order no longer exists; row marked as rolled back."
                )
                row.save(
                    update_fields=[
                        "status",
                        "linked_record_uid",
                        "linked_record_type",
                        "message",
                        "updated_at",
                    ]
                )

        remaining_imported = job.rows.filter(
            status=MigrationRowStatusChoices.IMPORTED
        ).count()
        rolled_back_rows = job.rows.filter(
            status=MigrationRowStatusChoices.ROLLED_BACK
        ).count()

        job.imported_rows = remaining_imported
        job.completed_at = timezone.now()
        if failed_purchases == 0 and remaining_imported == 0:
            job.status = MigrationStatusChoices.ROLLED_BACK
        else:
            job.status = MigrationStatusChoices.PARTIALLY_ROLLED_BACK
        job.save(
            update_fields=[
                "status",
                "imported_rows",
                "completed_at",
                "updated_at",
            ]
        )

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "rollback_completed",
                "reason": reason,
                "reversed_purchases": reversed_purchases,
                "failed_purchases": failed_purchases,
                "rolled_back_rows": rolled_back_rows,
            },
        )

        return {
            "implemented": True,
            "rolled_back": reversed_purchases > 0,
            "job_uid": str(job.uid),
            "status": job.status,
            "reversed_purchases": reversed_purchases,
            "failed_purchases": failed_purchases,
            "rolled_back_rows": rolled_back_rows,
            "errors": errors,
            "reason": reason,
        }
