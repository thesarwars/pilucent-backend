import logging

from django.db import transaction

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from wirehouseio.models import Warehouse
from wirehouseio.choicess import WarehouseStatusChoices

logger = logging.getLogger(__name__)


class LocationMigrationRollbackService:
    """
    Rolls back imported locations by soft-deleting the Warehouse record
    (status → REMOVED). No GL reversal is needed (has_gl_impact=False).
    """

    @staticmethod
    def run(job, user, reason="") -> dict:
        eligible_statuses = [
            MigrationStatusChoices.COMPLETED,
            MigrationStatusChoices.PARTIALLY_COMPLETED,
            MigrationStatusChoices.PARTIALLY_ROLLED_BACK,
        ]
        if job.status not in eligible_statuses:
            return {
                "implemented": True,
                "success": False,
                "message": (
                    f"Job status '{job.status}' is not eligible for rollback. "
                    f"Only completed or partially completed jobs can be rolled back."
                ),
            }

        imported_rows = list(
            job.rows.filter(
                status=MigrationRowStatusChoices.IMPORTED,
                linked_record_type="warehouse",
            )
        )

        if not imported_rows:
            return {
                "implemented": True,
                "success": False,
                "message": "No imported location rows found to roll back.",
            }

        rolled_back = 0
        failed = 0

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "location_rollback_started", "reason": reason},
        )

        for row in imported_rows:
            warehouse_uid = row.linked_record_uid
            try:
                with transaction.atomic():
                    warehouse = Warehouse.objects.filter(uid=warehouse_uid).first()
                    if warehouse:
                        warehouse.status = WarehouseStatusChoices.REMOVED
                        warehouse.save(update_fields=["status", "updated_at"])

                    row.status = MigrationRowStatusChoices.ROLLED_BACK
                    row.message = f"Rolled back. Reason: {reason}" if reason else "Rolled back."
                    row.save(update_fields=["status", "message", "updated_at"])

                    rolled_back += 1
                    MigrationAuditService.log(
                        job,
                        user,
                        CrudAction.DELETED,
                        {
                            "action": "location_rolled_back",
                            "warehouse_uid": warehouse_uid,
                        },
                    )

            except Exception as e:
                logger.exception(
                    "Location rollback failed for row %s (warehouse_uid=%s): %s",
                    row.uid,
                    warehouse_uid,
                    e,
                )
                failed += 1
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "location_rollback_failed",
                        "warehouse_uid": warehouse_uid,
                        "error": str(e),
                    },
                )

        # Determine final job status
        remaining_imported = job.rows.filter(
            status=MigrationRowStatusChoices.IMPORTED
        ).count()

        if remaining_imported == 0 and failed == 0:
            job.status = MigrationStatusChoices.ROLLED_BACK
        else:
            job.status = MigrationStatusChoices.PARTIALLY_ROLLED_BACK

        job.save(update_fields=["status", "updated_at"])

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "location_rollback_completed",
                "rolled_back": rolled_back,
                "failed": failed,
            },
        )

        return {
            "implemented": True,
            "success": failed == 0,
            "rolled_back": rolled_back,
            "failed": failed,
            "job_status": job.status,
        }
