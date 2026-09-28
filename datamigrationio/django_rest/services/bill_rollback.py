"""Reverse a data-migration bill import end-to-end.

What rolling back must accomplish:
  1. Restore every ChartOfAccount.opening_balance adjusted at import time.
  2. Restore the Supplier.opening_balance credit applied for the payable.
  3. Restore product quantities for any PRODUCT line items.
  4. Delete the JournalEntry rows (CASCADE removes connectors).
  5. Delete the Purchase (CASCADE removes PurchaseItem + address / currency connectors).
  6. Mark migration rows as ROLLED_BACK and flip job status.

Strategy: walk each JournalEntryConnector and call update_opening_balance
with the inverse kind to undo its side effect. Also explicitly reverse the
supplier balance since that is posted directly (not via connector).
"""

import logging
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from common.django_rest.helpers.balance_helpers import (
    get_migration_undo_balance_operation,
    update_opening_balance,
)
from common.django_rest.helpers.crud_logger import CrudAction
from journalio.choices import JournalEntryConnectorKindChoices
from journalio.models import JournalEntry, JournalEntryConnector
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


class BillMigrationRollbackService:
    """Roll back every Purchase (is_bill=True) created by a bill migration job."""

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
                "message": "No imported bill records were found to roll back.",
            }

        purchase_uid_to_rows = defaultdict(list)
        for row in imported_rows:
            purchase_uid_to_rows[row.linked_record_uid].append(row)

        purchases = list(
            Purchase.objects.filter(
                uid__in=purchase_uid_to_rows.keys(),
                company=job.company,
                is_bill=True,
            )
        )
        existing_purchase_uids = {str(p.uid) for p in purchases}

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "bill_rollback_started",
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
                    BillMigrationRollbackService._reverse_purchase(purchase)
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
                    "Bill rollback failed for purchase %s: %s", purchase_uid, exc
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
                        "action": "bill_rollback_purchase_failed",
                        "purchase_uid": purchase_uid,
                        "error": str(exc),
                    },
                )

        # Rows whose Purchase no longer exists — mark as rolled back
        for purchase_uid, rows in purchase_uid_to_rows.items():
            if purchase_uid in existing_purchase_uids:
                continue
            for row in rows:
                row.status = MigrationRowStatusChoices.ROLLED_BACK
                row.linked_record_uid = None
                row.linked_record_type = None
                row.message = "Linked bill no longer exists; row marked as rolled back."
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
                "action": "bill_rollback_completed",
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

    @staticmethod
    def _reverse_purchase(purchase):
        """Undo every opening-balance side effect produced by importing the bill,
        then delete its JournalEntry rows. Caller must wrap in atomic()."""
        journal_entries = list(JournalEntry.objects.filter(purchase=purchase))
        connectors = list(
            JournalEntryConnector.objects.filter(journal__in=journal_entries)
            .select_related("account", "purchase_item")
        )

        for original in connectors:
            BillMigrationRollbackService._reverse_connector(original)

        # Reverse supplier opening balance (billed as CREDIT on import, so reverse with DEBIT)
        BillMigrationRollbackService._reverse_supplier_balance(purchase)

        for journal_entry in journal_entries:
            journal_entry.delete()

    @staticmethod
    def _reverse_connector(original):
        account = original.account
        if account is None:
            return

        amount = original.debit if original.debit else original.credit
        if not amount:
            return

        undo_op = get_migration_undo_balance_operation(account, original.kind)
        update_opening_balance(
            account,
            undo_op,
            amount,
            account.opening_balance,
        )

        # Restore product quantity if this connector tracked a purchase item
        purchase_item = original.purchase_item
        if (
            purchase_item is not None
            and purchase_item.purchase_price
            and Decimal(purchase_item.purchase_price) > 0
            and original.credit
            and Decimal(original.credit) > 0
        ):
            try:
                restore_qty = int(
                    (Decimal(original.credit) / Decimal(purchase_item.purchase_price))
                    .to_integral_value()
                )
            except Exception:
                restore_qty = 0
            if restore_qty > 0:
                purchase_item.quantity = (purchase_item.quantity or 0) - restore_qty
                if purchase_item.quantity < 0:
                    purchase_item.quantity = 0
                purchase_item.save(update_fields=["quantity"])

    @staticmethod
    def _reverse_supplier_balance(purchase):
        """Reverse the supplier opening balance credit applied when the bill was created."""
        supplier = purchase.supplier
        if supplier is None:
            return
        due_total = Decimal(purchase.due_total or 0)
        if due_total == 0:
            return
        # Import called update_opening_balance(supplier, CREDIT, due_total)
        # Reverse with DEBIT
        update_opening_balance(
            supplier,
            JournalEntryConnectorKindChoices.DEBIT,
            due_total,
            supplier.opening_balance,
        )
