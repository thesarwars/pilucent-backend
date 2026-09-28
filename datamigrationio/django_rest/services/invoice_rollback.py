"""Reverse a data-migration invoice import end-to-end.

What rolling back must accomplish:
  1. Restore every `ChartOfAccount.opening_balance` that
     `MigrationInvoiceCreateService.create_invoice` adjusted at import time.
  2. Restore the FIFO-deducted `PurchaseItem.quantity` for each line
     consumed from inventory.
  3. Restore the `Customer.opening_balance` credit applied for the
     receivable.
  4. Delete the `JournalEntry` rows for each rolled-back Sale (CASCADE
     removes their connectors).
  5. Delete the Sale (CASCADE removes SaleItem + the address / currency /
     term connectors).
  6. Mark the migration rows as ROLLED_BACK and flip the job status.

Strategy mirrors `payrollio/django_rest/helpers/void_payroll.py` — walk
each `JournalEntryConnector` and call `update_opening_balance` with the
inverse `kind` to undo its side effect. We skip writing sibling reversal
connectors: a migration rollback is "undo a bad import", not a business
event, so a clean delete is preferred to a balanced paper trail.

Caller is expected to keep each Sale's reversal inside `transaction.atomic`
— partial reversal would leave the GL inconsistent. A failure on one Sale
must not abort the rollback of the others.
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


class InvoiceMigrationRollbackService:
    """Roll back every Sale created by an invoice-migration job."""

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
                    InvoiceMigrationRollbackService._reverse_sale(sale)
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

        # Rows whose Sale no longer exists — treat as already-rolled-back so
        # the job state stays consistent.
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reverse_sale(sale):
        """Undo every opening-balance side effect produced by importing `sale`,
        then delete its JournalEntry rows. Caller must wrap in atomic().
        """
        journal_entries = list(JournalEntry.objects.filter(sale=sale))
        connectors = list(
            JournalEntryConnector.objects.filter(journal__in=journal_entries)
            .select_related("account", "purchase_item")
        )

        for original in connectors:
            InvoiceMigrationRollbackService._reverse_connector(original)

        InvoiceMigrationRollbackService._reverse_customer_balance(sale)

        # CASCADE removes connectors when the journal entry is deleted.
        for journal_entry in journal_entries:
            journal_entry.delete()

    @staticmethod
    def _reverse_connector(original):
        account = original.account
        if account is None:
            return

        # One of debit/credit is 0 — pick the non-zero side.
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

        # Restore FIFO-deducted PurchaseItem.quantity. The asset-account
        # connector for a deducted PI carries cost = qty * purchase_price; we
        # infer qty and add it back. Only connectors with a CREDIT side
        # represent the substraction posted by `fifo_product_deduction`.
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
        # Importer called update_opening_balance(customer, "credit", due_total)
        # — reverse with the inverse kind.
        update_opening_balance(
            customer,
            JournalEntryConnectorKindChoices.DEBIT,
            due_total,
            customer.opening_balance,
        )
