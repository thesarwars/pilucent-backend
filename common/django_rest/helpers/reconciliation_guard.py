"""Refuse to disturb a line that a closed reconciliation has signed off.

Nothing outside the reconciliation module reads
`JournalEntryConnector.reconciliation` as a precondition for anything, so a
document whose bank leg was ticked and closed can still be edited or deleted.
Its session's stored `difference` was zero when it closed and nothing recomputes
it, so the session goes on asserting that it balanced against lines that have
since moved. A reconciliation that has been signed off is meant to be a fixed
point; without this it is a snapshot of a moving target.

Keyed on the **session's** status, never on the FK being set. A line can be left
pointing at an UNDONE session -- undo releases through `candidate_connectors`,
which also filters `journal__status` and the statement date -- and an undone
session is precisely one the user has already unlocked on purpose.

The escape hatch already exists and is named in the error: undo the
reconciliation, which is LIFO, then make the change.
"""

from rest_framework.serializers import ValidationError


class ReconciledLineLocked(ValidationError):
    """409-shaped refusal: the line belongs to a closed reconciliation."""


def closed_reconciliations_for(entries):
    """The distinct CLOSED sessions holding any leg of `entries`."""
    from journalio.models import JournalEntryConnector
    from transactionio.choices import BankReconciliationStatusChoices

    if not entries:
        return []

    return list(
        {
            leg.reconciliation
            for leg in JournalEntryConnector.objects.filter(
                journal__in=entries, reconciliation__isnull=False
            ).select_related("reconciliation")
            if leg.reconciliation
            and leg.reconciliation.status == BankReconciliationStatusChoices.CLOSED
        }
    )


def assert_not_reconciled(entries, *, action="change"):
    """Raise unless every leg of `entries` is free of a closed reconciliation.

    `action` is the verb used in the message -- "delete" or "change" -- because
    a refusal that does not say what it refused is a worse error than the state
    it is protecting.
    """
    sessions = closed_reconciliations_for(entries)
    if not sessions:
        return

    named = ", ".join(
        f"{session.bank_account.title} through {session.statement_ending_date}"
        for session in sorted(sessions, key=lambda s: s.statement_ending_date)
    )
    raise ReconciledLineLocked(
        {
            "code": "LEDGER-RECONCILED",
            "message": (
                f"This document cannot be {action}d: part of it is reconciled "
                f"against a closed statement ({named}). Undo that reconciliation "
                f"first — reconciliations undo newest first."
            ),
            "reconciliations": [
                {
                    "uid": str(session.uid),
                    "bank_account": session.bank_account.title,
                    "statement_ending_date": str(session.statement_ending_date),
                }
                for session in sorted(
                    sessions, key=lambda s: s.statement_ending_date, reverse=True
                )
            ],
        }
    )
