"""Undoing a bank-feed match moved five of ten account kinds the wrong way.

`PATCH /we/transactions/csv/update` with `{"undo": true}` reversed the journal
entry a matched statement row had created, and did it by hard-coding the leg's
accounting side as the balance operation:

    if kind == "DEBIT":
        update_opening_balance(account, "DEBIT", debit, 0)

`update_opening_balance`'s second argument is not an accounting side. It is
add/subtract against the stored balance in the account's **own** direction, and
its docstring says so. So:

* ASSETS and EXPENSES — a DEBIT leg posts an addition, and undoing with DEBIT
  subtracts. Correct, which is why nobody noticed.
* LIABILITIES, EQUITIES, INCOMES — a DEBIT leg posts a *subtraction*, and undoing
  with DEBIT subtracted again. **Wrong, by twice the amount.**

Five of the ten kind x side combinations. That is the same shape as the payroll
`_post_side` defect whose history produced the exact sign inversions repaired on
production, and `inverse_balance_operation` already existed for it — its
docstring names the failure: "amend paths kept hard-coding the undo. That is
correct only while the account is the kind the author pictured."

It then hard-deleted the entry, so nothing survived to measure the damage
against. Both halves are fixed by routing through `void_manual_journal_entry`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.helpers.journal_entry_posting import void_manual_journal_entry


class UndoDirectionTests(TestCase):
    """One posted leg per account kind, undone, balance back where it started."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")

    def account(self, kind, side):
        """A unique title per (kind, side) -- `unique_title_per_company_ci`."""
        return ChartOfAccount.objects.create(
            company=self.company, title=f"{kind} {side}", code=f"{kind[:4]}{side[:2]}",
            kind=kind, status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("1000"),
        )

    def post_and_undo(self, kind, side):
        """Post one leg the way the feed does, then undo it. Returns the delta."""
        from common.django_rest.helpers.balance_helpers import (
            action_for_side,
            balance_operation_for_action,
            update_opening_balance,
        )

        account = self.account(kind, side)
        amount = Decimal("250")

        # Post exactly as `transaction_rule_apply` does: derive the operation
        # from the side against the account's kind.
        update_opening_balance(
            account,
            balance_operation_for_action(action_for_side(kind, side)),
            amount,
            0,
        )
        account.refresh_from_db()
        after_posting = account.opening_balance

        entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.JOURNAL_ENTRY,
            status=JournalEntryStatusChoices.PUBLISHED, date=date(2026, 3, 1),
            amount=amount,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account, date=date(2026, 3, 1),
            debit=amount if side == JournalEntryConnectorKindChoices.DEBIT else 0,
            credit=amount if side == JournalEntryConnectorKindChoices.CREDIT else 0,
            kind=side,
        )

        void_manual_journal_entry(entry)

        account.refresh_from_db()
        return after_posting, account.opening_balance, entry

    def test_every_kind_and_side_returns_to_its_starting_balance(self):
        """All ten combinations. Five of them used to move the wrong way."""
        for kind in [
            ChartOfAccountKindChoices.ASSETS,
            ChartOfAccountKindChoices.EXPENSES,
            ChartOfAccountKindChoices.LIABILITIES,
            ChartOfAccountKindChoices.EQUITIES,
            ChartOfAccountKindChoices.INCOMES,
        ]:
            for side in (
                JournalEntryConnectorKindChoices.DEBIT,
                JournalEntryConnectorKindChoices.CREDIT,
            ):
                with self.subTest(kind=kind, side=side):
                    posted, undone, _ = self.post_and_undo(kind, side)
                    self.assertEqual(
                        undone, Decimal("1000.000"),
                        f"{kind} with a {side} leg: posted to {posted}, undone "
                        f"to {undone}, should be back at 1000",
                    )

    def test_the_undo_never_overshoots_in_the_same_direction(self):
        """The specific failure: subtracting twice instead of adding back."""
        posted, undone, _ = self.post_and_undo(
            ChartOfAccountKindChoices.INCOMES,
            JournalEntryConnectorKindChoices.DEBIT,
        )
        self.assertEqual(posted, Decimal("750.000"))   # a debit lowers income
        self.assertEqual(undone, Decimal("1000.000"))  # used to land at 500

    def test_the_entry_is_reversed_rather_than_erased(self):
        _posted, _undone, entry = self.post_and_undo(
            ChartOfAccountKindChoices.ASSETS,
            JournalEntryConnectorKindChoices.DEBIT,
        )

        self.assertTrue(JournalEntry.objects.filter(pk=entry.pk).exists())
        reversal = JournalEntry.objects.exclude(pk=entry.pk).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 1)
        self.assertEqual(
            legs.first().request_kind,
            JournalEntryConnectorRequestKindChoices.DELETED,
        )
        self.assertEqual(reversal.status, JournalEntryStatusChoices.REMOVED)

    def test_undoing_twice_does_not_double_reverse(self):
        _posted, _undone, entry = self.post_and_undo(
            ChartOfAccountKindChoices.LIABILITIES,
            JournalEntryConnectorKindChoices.CREDIT,
        )
        account = ChartOfAccount.objects.filter(company=self.company).get()

        void_manual_journal_entry(entry)

        account.refresh_from_db()
        self.assertEqual(account.opening_balance, Decimal("1000.000"))


class TheCsvUndoUsesTheSharedHelperTests(TestCase):
    """Structural: the hard-coded loop must not come back."""

    def test_it_does_not_hard_code_the_balance_operation(self):
        from pathlib import Path

        source = Path(
            "weapi/django_rest/serializers/transactions/csv_transactions.py"
        ).read_text()
        undo = source.split("if undo:")[1].split("def ")[0]

        self.assertIn("void_manual_journal_entry(", undo)
        self.assertNotIn('update_opening_balance(\n', undo)
        self.assertNotIn(".delete()", undo)
