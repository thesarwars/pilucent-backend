"""Reverse a data-migration sales receipt import end-to-end.

Same strategy as invoice rollback: walk `JournalEntryConnector` rows,
call `update_opening_balance` with inverse kind, restore FIFO purchase
quantities, reverse any customer balance change, delete journal entries
and the `Sale`, then mark migration rows ROLLED_BACK.

See `MigrationSaleReceiptCreateService.create_receipt` for what is posted.
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


class SalesReceiptMigrationRollbackService:
    """Roll back every Sale created by a sales-receipt migration job."""

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
                "message": "No imported sale records were found to roll back.",
            }

        sale_uid_to_rows = defaultdict(list)
        for row in imported_rows:
            sale_uid_to_rows[row.linked_record_uid].append(row)

        sales = list(
            Sale.objects.filter(
                uid__in=sale_uid_to_rows.keys(),
                company=job.company,
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
                    SalesReceiptMigrationRollbackService._reverse_sale(sale)
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

        for sale_uid, rows in sale_uid_to_rows.items():
            if sale_uid in existing_sale_uids:
                continue
            for row in rows:
                row.status = MigrationRowStatusChoices.ROLLED_BACK
                row.linked_record_uid = None
                row.linked_record_type = None
                row.message = "Linked sale no longer exists; row marked as rolled back."
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

    @staticmethod
    def _reverse_sale(sale):
        journal_entries = list(JournalEntry.objects.filter(sale=sale))
        connectors = list(
            JournalEntryConnector.objects.filter(journal__in=journal_entries)
            .select_related("account", "purchase_item")
        )

        for original in connectors:
            SalesReceiptMigrationRollbackService._reverse_connector(original)

        SalesReceiptMigrationRollbackService._reverse_customer_balance(sale)

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
                purchase_item.quantity = (purchase_item.quantity or 0) + restore_qty
                purchase_item.save(update_fields=["quantity"])

    @staticmethod
    def _reverse_customer_balance(sale):
        customer = sale.customer
        if customer is None:
            return
        due_total = Decimal(sale.due_total or 0)
        if due_total == 0:
            return
        update_opening_balance(
            customer,
            JournalEntryConnectorKindChoices.DEBIT,
            due_total,
            customer.opening_balance,
        )
