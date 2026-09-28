"""Reverse a data-migration expense import end-to-end.

What rolling back must accomplish:
  1. Restore every ChartOfAccount.opening_balance adjusted at import time.
  2. Restore the payment account balance (expenses debit the payment account on import).
  3. Restore product quantities for any PRODUCT line items.
  4. Delete the JournalEntry rows (CASCADE removes connectors).
  5. Delete the Expense (CASCADE removes ExpenseConnector and the linked Purchase records).
  6. Mark migration rows as ROLLED_BACK and flip job status.

Strategy: walk each JournalEntryConnector and call update_opening_balance
with the inverse kind to undo its side effect. The journal entry is linked
to the Expense record (expense FK), not the Purchase.
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
from purchaseio.models import Expense

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


class ExpenseMigrationRollbackService:
    """Roll back every Expense created by an expense migration job."""

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
                linked_record_type="expense",
            )
        )

        if not imported_rows:
            return {
                "implemented": True,
                "rolled_back": False,
                "job_uid": str(job.uid),
                "status": job.status,
                "message": "No imported expense records were found to roll back.",
            }

        expense_uid_to_rows = defaultdict(list)
        for row in imported_rows:
            expense_uid_to_rows[row.linked_record_uid].append(row)

        expenses = list(
            Expense.objects.filter(
                uid__in=expense_uid_to_rows.keys(),
                supplier__company=job.company,
            )
        )
        existing_expense_uids = {str(e.uid) for e in expenses}

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "expense_rollback_started",
                "reason": reason,
                "expenses_targeted": len(expense_uid_to_rows),
            },
        )

        reversed_expenses = 0
        failed_expenses = 0
        errors = []

        for expense in expenses:
            expense_uid = str(expense.uid)
            try:
                with transaction.atomic():
                    ExpenseMigrationRollbackService._reverse_expense(expense)
                    expense.delete()

                for row in expense_uid_to_rows.get(expense_uid, []):
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
                reversed_expenses += 1
            except Exception as exc:
                logger.exception(
                    "Expense rollback failed for expense %s: %s", expense_uid, exc
                )
                failed_expenses += 1
                errors.append({"expense_uid": expense_uid, "error": str(exc)})
                for row in expense_uid_to_rows.get(expense_uid, []):
                    row.message = f"Rollback failed: {exc}"[:500]
                    row.save(update_fields=["message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "expense_rollback_expense_failed",
                        "expense_uid": expense_uid,
                        "error": str(exc),
                    },
                )

        # Rows whose Expense no longer exists — mark as rolled back
        for expense_uid, rows in expense_uid_to_rows.items():
            if expense_uid in existing_expense_uids:
                continue
            for row in rows:
                row.status = MigrationRowStatusChoices.ROLLED_BACK
                row.linked_record_uid = None
                row.linked_record_type = None
                row.message = "Linked expense no longer exists; row marked as rolled back."
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
        if failed_expenses == 0 and remaining_imported == 0:
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
                "action": "expense_rollback_completed",
                "reason": reason,
                "reversed_expenses": reversed_expenses,
                "failed_expenses": failed_expenses,
                "rolled_back_rows": rolled_back_rows,
            },
        )

        return {
            "implemented": True,
            "rolled_back": reversed_expenses > 0,
            "job_uid": str(job.uid),
            "status": job.status,
            "reversed_expenses": reversed_expenses,
            "failed_expenses": failed_expenses,
            "rolled_back_rows": rolled_back_rows,
            "errors": errors,
            "reason": reason,
        }

    @staticmethod
    def _reverse_expense(expense):
        """Undo every opening-balance side effect produced by importing the expense,
        then delete its JournalEntry rows. Caller must wrap in atomic().

        JournalEntry is linked via expense FK (kind=EXPENSE), not purchase FK.
        Deleting the Expense via expense.delete() will CASCADE to ExpenseConnector
        and then to the linked Purchase records."""
        journal_entries = list(JournalEntry.objects.filter(expense=expense))
        connectors = list(
            JournalEntryConnector.objects.filter(journal__in=journal_entries)
            .select_related("account", "purchase_item")
        )

        for original in connectors:
            ExpenseMigrationRollbackService._reverse_connector(original)

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
