"""Reverse a finalized payroll run end-to-end.

What "voiding" must accomplish:
  1. Stop the run from counting toward Year-to-Date totals.
  2. Stop the run from counting toward tax-liability reports.
  3. Restore every `ChartOfAccount.opening_balance` that
     `post_payroll_entries` adjusted when the run was finalized.
  4. Leave a paper trail on the GL: the original journal items stay,
     accompanied by offsetting items so any historical query still ties
     back to a debit/credit-balanced entry.

(1) and (2) are free once `payroll.status = VOIDED` because the queryset
filters added in step 8 of the YTD work already exclude voided runs.
(3) and (4) are why this helper exists.

Strategy: walk every `JournalEntryConnector` linked to the payroll's
`JournalEntry`, write a sibling connector with debit↔credit swapped, and undo
the original balance side effect. After this returns, `account.opening_balance`
is exactly what it was before `post_payroll_entries` ran.

⚠️ The two halves need DIFFERENT values, which is what this used to get wrong.
The sibling connector takes the opposite accounting SIDE. The balance undo does
not: `update_opening_balance` reads its CREDIT/DEBIT argument as add/subtract,
so passing the opposite side there adds again on any debit-natural account. A
wage expense posts DEBIT and adds; its inverse side is CREDIT, which also adds.
Voiding doubled every wage, tax and asset account instead of clearing it.
`get_migration_undo_balance_operation` answers the question actually being
asked -- what operation reverses what this connector did -- and is what the
balance call uses.
"""

import logging
from decimal import Decimal


logger = logging.getLogger(__name__)


def reverse_payroll_entries(payroll_instance, *, actor=None, reason=None):
    """Mark `payroll_instance` VOIDED and reverse its journal items.

    Caller is expected to wrap this in `transaction.atomic()` — partial
    reversal would leave the GL inconsistent. Raises `ValueError` if the
    run isn't currently FINALIZED (DRAFT runs should be deleted, not
    voided; already-VOIDED runs are no-ops the caller should reject).

    Returns a small dict summarizing what was reversed, suitable for
    inclusion in the API response.
    """
    # Lazy imports keep `payrollio` from pulling `journalio` / `common`
    # helpers at module load.
    from payrollio.choicess import PayrollSalaryProcessStatusChoices
    from journalio.models import JournalEntry, JournalEntryConnector
    from journalio.choices import (
        JournalEntryConnectorKindChoices,
        JournalEntryConnectorRequestKindChoices,
    )
    from common.django_rest.helpers.balance_helpers import (
        get_migration_undo_balance_operation,
        update_opening_balance,
    )
    from common.django_rest.helpers.crud_logger import CrudAction, crud_log

    if payroll_instance.status != PayrollSalaryProcessStatusChoices.FINALIZED:
        raise ValueError(
            f"Only FINALIZED payroll runs can be voided "
            f"(current status: {payroll_instance.status})."
        )

    journal_entry = JournalEntry.objects.filter(
        payroll_salary=payroll_instance
    ).first()

    description = f"Reversal of payroll {payroll_instance.uid}"
    if reason:
        description = f"{description}: {reason}"

    connectors_reversed = 0

    if journal_entry is not None:
        # `description__startswith=...` defends against double-voiding the
        # same run if someone re-points the FK and re-runs this helper.
        original_connectors = list(
            JournalEntryConnector.objects.filter(journal=journal_entry)
            .exclude(description__startswith="Reversal of payroll")
            .select_related("account")
        )

        for original in original_connectors:
            # One of debit/credit is 0 — pick the non-zero side.
            amount = original.debit if original.debit else original.credit
            if not amount:
                # Defensive: a connector with both sides zero has no effect
                # to undo. Skip rather than write a no-op reversal row.
                continue

            inverse_kind = (
                JournalEntryConnectorKindChoices.CREDIT
                if original.kind == JournalEntryConnectorKindChoices.DEBIT
                else JournalEntryConnectorKindChoices.DEBIT
            )

            # Undo the side effect this connector had on the account balance
            # when the run was originally posted.
            #
            # NOT `inverse_kind`. That is the opposite accounting SIDE, which is
            # exactly right for the reversing connector below -- but
            # `update_opening_balance` reads its CREDIT/DEBIT argument as
            # add/subtract, not as a side. A wage expense posts as a DEBIT
            # connector and ADDS to the stored balance; `inverse_kind` for it is
            # CREDIT, which adds again. Voiding a run doubled every
            # debit-natural account instead of clearing it.
            #
            # `get_migration_undo_balance_operation` derives the original
            # operation from (account kind, stored connector kind) and inverts
            # that, which is the question actually being asked here.
            update_opening_balance(
                original.account,
                get_migration_undo_balance_operation(
                    original.account, original.kind
                ),
                amount,
                original.account.opening_balance,
            )

            # Sibling connector that nets the original to zero. Keeps the
            # GL trial-balance consistent without deleting history.
            JournalEntryConnector.objects.create(
                journal=journal_entry,
                account=original.account,
                employee=original.employee,
                debit=original.credit,  # swapped
                credit=original.debit,
                kind=inverse_kind,
                request_kind=JournalEntryConnectorRequestKindChoices.DELETED,
                description=description,
                total=original.total,
                last_balance=original.account.opening_balance,
                transaction_id=original.transaction_id,
            )
            connectors_reversed += 1

    # Flipping status here means the YTD helper and the Tax Center
    # queryset will already exclude this run on their next read.
    payroll_instance.status = PayrollSalaryProcessStatusChoices.VOIDED
    payroll_instance.save(update_fields=["status"])

    crud_log(
        logger,
        CrudAction.UPDATED,
        payroll_instance,
        actor=actor,
        extra={
            "event": "PAYROLL_VOIDED",
            "reason": reason or "(none provided)",
            "connectors_reversed": connectors_reversed,
            "had_journal_entry": journal_entry is not None,
        },
    )

    return {
        "uid": str(payroll_instance.uid),
        "status": payroll_instance.status,
        "connectors_reversed": connectors_reversed,
        "had_journal_entry": journal_entry is not None,
    }
