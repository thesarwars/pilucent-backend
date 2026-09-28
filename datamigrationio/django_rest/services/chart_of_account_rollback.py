import logging
from decimal import Decimal

from django.db import transaction

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.crud_logger import CrudAction

from journalio.models import JournalEntry, JournalEntryConnector

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService

logger = logging.getLogger(__name__)

GL_KINDS = {
    ChartOfAccountKindChoices.ASSETS,
    ChartOfAccountKindChoices.LIABILITIES,
    ChartOfAccountKindChoices.EQUITIES,
}


class ChartOfAccountMigrationRollbackService:
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
                linked_record_type="chart_of_account",
            )
        )

        if not imported_rows:
            return {
                "implemented": True,
                "success": False,
                "message": "No imported chart of account rows found to roll back.",
            }

        rolled_back = 0
        failed = 0

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "coa_rollback_started", "reason": reason},
        )

        # Pre-fetch OBE once — we'll adjust its balance as we go
        chart_of_accounts = get_chart_of_account(["Opening Balance Equity"], job.company)
        obe = chart_of_accounts.get("Opening Balance Equity")

        for row in imported_rows:
            coa_uid = row.linked_record_uid
            nd = row.normalized_data or {}

            try:
                with transaction.atomic():
                    # --- 1. Reverse journal entry (opening balance) if present ---
                    je_uid = nd.get("journal_entry_uid")
                    if je_uid:
                        je = JournalEntry.objects.filter(uid=je_uid).first()
                        if je and obe:
                            connectors = list(
                                JournalEntryConnector.objects.filter(journal=je)
                            )
                            # Restore OBE opening_balance by reversing what was done at import:
                            # At import: ASSETS/LIABILITIES → obe.opening_balance += ob
                            #            EQUITIES          → obe.opening_balance -= ob
                            # Rollback is the inverse.
                            for conn in connectors:
                                if conn.account_id == obe.id:
                                    # credit means OBE was credited (ASSETS/LIABILITIES path)
                                    # debit means OBE was debited (EQUITIES path)
                                    obe.opening_balance -= Decimal(str(conn.credit or 0))
                                    obe.opening_balance += Decimal(str(conn.debit or 0))

                            obe.save_dirty_fields()

                            JournalEntryConnector.objects.filter(journal=je).delete()
                            je.delete()

                            logger.info(
                                "[COA ROLLBACK] Reversed journal entry uid=%s for coa_uid=%s",
                                je_uid,
                                coa_uid,
                            )

                    # --- 2. Soft-delete the ChartOfAccount ---
                    coa = ChartOfAccount.objects.filter(uid=coa_uid).first()
                    if coa:
                        coa.status = ChartOfAccountStatusChoices.REMOVED
                        coa.save(update_fields=["status", "updated_at"])

                    row.status = MigrationRowStatusChoices.ROLLED_BACK
                    row.message = f"Rolled back. Reason: {reason}" if reason else "Rolled back."
                    row.save(update_fields=["status", "message", "updated_at"])

                    rolled_back += 1
                    MigrationAuditService.log(
                        job,
                        user,
                        CrudAction.DELETED,
                        {
                            "action": "coa_rolled_back",
                            "coa_uid": coa_uid,
                            "journal_entry_uid": je_uid,
                        },
                    )

            except Exception as exc:
                logger.exception(
                    "[COA ROLLBACK] FAILED row=%s coa_uid=%s: %s", row.uid, coa_uid, exc
                )
                failed += 1
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "coa_rollback_failed",
                        "coa_uid": coa_uid,
                        "error": str(exc),
                    },
                )

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
                "action": "coa_rollback_completed",
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
