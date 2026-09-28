import logging

from django.db import transaction

from employeeio.choices import EmployeeStatusChoices
from employeeio.models import Employee

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

logger = logging.getLogger(__name__)


class EmployeeMigrationRollbackService:
    """
    Rolls back imported employees by:
      - Setting Employee.status = REMOVED
      - Deactivating the linked User (is_active = False)
    No GL reversal is needed (has_gl_impact=False).
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
                    "Only completed or partially completed jobs can be rolled back."
                ),
            }

        imported_rows = list(
            job.rows.filter(
                status=MigrationRowStatusChoices.IMPORTED,
                linked_record_type="employee",
            )
        )

        if not imported_rows:
            return {
                "implemented": True,
                "success": False,
                "message": "No imported employee rows found to roll back.",
            }

        rolled_back = 0
        failed = 0

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "employee_rollback_started", "reason": reason},
        )

        for row in imported_rows:
            employee_uid = row.linked_record_uid
            try:
                with transaction.atomic():
                    employee = Employee.objects.filter(uid=employee_uid).first()
                    if employee:
                        employee.status = EmployeeStatusChoices.REMOVED
                        employee.save(update_fields=["status", "updated_at"])
                        # sync_employee_status_to_user signal handles user deactivation

                    row.status = MigrationRowStatusChoices.ROLLED_BACK
                    row.message = (
                        f"Rolled back. Reason: {reason}" if reason else "Rolled back."
                    )
                    row.save(update_fields=["status", "message", "updated_at"])

                    rolled_back += 1
                    MigrationAuditService.log(
                        job,
                        user,
                        CrudAction.DELETED,
                        {
                            "action": "employee_rolled_back",
                            "employee_uid": employee_uid,
                        },
                    )

            except Exception as e:
                logger.exception(
                    "Employee rollback failed for row %s (employee_uid=%s): %s",
                    row.uid,
                    employee_uid,
                    e,
                )
                failed += 1
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "employee_rollback_failed",
                        "employee_uid": employee_uid,
                        "error": str(e),
                    },
                )

        remaining_imported = job.rows.filter(
            status=MigrationRowStatusChoices.IMPORTED,
            linked_record_type="employee",
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
                "action": "employee_rollback_completed",
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
