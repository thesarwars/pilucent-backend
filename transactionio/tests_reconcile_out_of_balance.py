"""A reconciliation closed at any difference, silently.

Spec BLZ-FIN-REG-SPEC-001 s16.4 and acceptance criterion UR-06: Finish is
available only at a difference of 0.00. Ours had no such rule.

The difference was computed, and correctly -- but only in the summary endpoint.
Closing went through a different serializer that never consulted it, and whose
whole body was:

    self.transactions.update(is_matched=True)
    self.reconciliation.status = CLOSED
    self.reconciliation.reconciled_on = datetime.today().date()

So a session could be declared reconciled while the books and the bank
disagreed, with no discrepancy posting, no reason, no flag, and nothing on the
record to show they ever did.

Closing out of balance is still reachable, because refusing outright strands
anyone with a genuine unexplained item. It is now the documented exception:
`force` plus a reason, the difference posted to Reconciliation Discrepancies so
the ledger still balances, and the session marked forced.

Gap #41 of `CHART_OF_ACCOUNTS_GAPS.md`; P0.2 of `COA_FIX_PLAN_V3.md`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices,
)
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import JournalEntryConnectorKindChoices, JournalEntryKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

from transactionio.choices import BankReconciliationStatusChoices

from transactionio.models import BankReconciliation, TransactionInformation


class FakeRequest:
    def __init__(self, user):
        self.user = user


class OutOfBalanceFinishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.user = User.objects.create_user(
            name="A", email="a@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def setUp(self):
        super().setUp()
        self.bank = ChartOfAccount.objects.create(
            company=self.company, title="Acme Operating", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )
        # The other side of every fixture document, so entries balance.
        self.counterpart = ChartOfAccount.objects.create(
            company=self.company, title="Acme Sales", code="4000",
            kind=ChartOfAccountKindChoices.INCOMES,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )

    def reconciliation(self, statement_ending=Decimal("100"), on=None):
        """`on` is a parameter because two sessions on one account must differ.

        `unique_reconciliation_per_account_period` (BR-15) forbids two sessions
        sharing an account and a statement date, which is the point of it -- so
        a test that opens a second session has to date it differently.
        """
        return BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            beginning_balance=Decimal("0"),
            statement_ending_balance=statement_ending,
            statement_ending_date=on or date(2026, 8, 1),
        )

    def txn(self, received=Decimal("0"), spent=Decimal("0"), on=None):
        """A posted document with a leg on the bank account.

        Was a `TransactionInformation` row -- an imported statement line. Phase
        3 made the ledger the candidate set, so a statement row is no longer
        something a session can tick, and this suite would otherwise be
        asserting the zero-difference rule against a table the rule no longer
        reads.

        Two legs, so the entry balances and is a legitimate document rather
        than a fixture that only looks like one.
        """
        from journalio.choices import (
            JournalEntryConnectorKindChoices,
            JournalEntryConnectorRequestKindChoices,
            JournalEntryKindChoices,
            JournalEntryStatusChoices,
        )

        amount = received or spent
        when = on or date(2026, 7, 1)
        entry = JournalEntry.objects.create(
            company=self.company,
            date=when,
            amount=amount,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=(
                JournalEntryKindChoices.BANK_DEPOSIT
                if received
                else JournalEntryKindChoices.EXPENSE
            ),
        )
        DEBIT = JournalEntryConnectorKindChoices.DEBIT
        CREDIT = JournalEntryConnectorKindChoices.CREDIT
        CREATED = JournalEntryConnectorRequestKindChoices.CREATED
        JournalEntryConnector.objects.create(
            journal=entry, account=self.bank, date=when,
            debit=received, credit=spent,
            kind=DEBIT if received else CREDIT,
            request_kind=CREATED, total=amount,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=self.counterpart, date=when,
            debit=spent, credit=received,
            kind=CREDIT if received else DEBIT,
            request_kind=CREATED, total=amount,
        )
        return entry

    def finish(self, recon, txns, **extra):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        return PrivateWeTransactionMatchSerializer(
            data={
                "reconciliation_id": str(recon.uid),
                # Journal entries now -- see `txn` above.
                "journal_entry_ids": [str(t.uid) for t in txns],
                **extra,
            },
            context={"request": FakeRequest(self.user)},
        )

    # ------------------------------------------------------------- the rule

    def test_a_balanced_session_closes(self):
        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("100"))

        serializer = self.finish(recon, [txn])
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        recon.refresh_from_db()
        self.assertEqual(recon.status, BankReconciliationStatusChoices.CLOSED)
        self.assertFalse(recon.is_forced)

    def test_an_out_of_balance_session_is_refused(self):
        from rest_framework.serializers import ValidationError

        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))  # 40 short

        serializer = self.finish(recon, [txn])
        serializer.is_valid(raise_exception=True)
        with self.assertRaises(ValidationError):
            serializer.save()

        recon.refresh_from_db()
        self.assertNotEqual(
            recon.status, BankReconciliationStatusChoices.CLOSED,
            "closed while out of balance by 40",
        )

    def test_the_refusal_rolls_back_the_matching(self):
        """`save()` ticks the lines before it can know the difference."""
        from rest_framework.serializers import ValidationError

        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))

        serializer = self.finish(recon, [txn])
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except ValidationError:
            pass

        # The tick now lands on the ledger leg, not on a statement row.
        still_cleared = JournalEntryConnector.objects.filter(
            journal=txn, account=self.bank, reconciliation__isnull=False
        ).exists()
        self.assertFalse(
            still_cleared, "a refused close left its ledger legs cleared"
        )

    def test_the_refusal_names_the_amount(self):
        from rest_framework.serializers import ValidationError

        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))

        serializer = self.finish(recon, [txn])
        serializer.is_valid(raise_exception=True)
        with self.assertRaises(ValidationError) as caught:
            serializer.save()

        self.assertIn("40", str(caught.exception))

    # ---------------------------------------------------------- force finish

    def test_force_without_a_reason_is_refused(self):
        from rest_framework.serializers import ValidationError

        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))

        serializer = self.finish(recon, [txn], force=True, forced_reason="   ")
        serializer.is_valid(raise_exception=True)
        with self.assertRaises(ValidationError):
            serializer.save()

        recon.refresh_from_db()
        self.assertNotEqual(recon.status, BankReconciliationStatusChoices.CLOSED)

    def test_force_with_a_reason_closes_and_records_why(self):
        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))

        serializer = self.finish(
            recon, [txn], force=True, forced_reason="Bank fee not yet booked"
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        recon.refresh_from_db()
        self.assertEqual(recon.status, BankReconciliationStatusChoices.CLOSED)
        self.assertTrue(recon.is_forced)
        self.assertEqual(recon.forced_reason, "Bank fee not yet booked")
        self.assertEqual(Decimal(str(recon.forced_difference)), Decimal("40.00"))

    def test_forcing_posts_a_balanced_entry_to_discrepancies(self):
        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))

        serializer = self.finish(recon, [txn], force=True, forced_reason="fee")
        serializer.is_valid(raise_exception=True)
        serializer.save()

        entry = JournalEntry.objects.get(
            company=self.company, kind=JournalEntryKindChoices.BANK_RECONCILIATION
        )
        self.assertEqual(entry.bank_reconciliation_id, recon.pk)

        legs = JournalEntryConnector.objects.filter(journal=entry)
        self.assertEqual(legs.count(), 2)
        debits = sum(Decimal(str(l.debit or 0)) for l in legs)
        credits = sum(Decimal(str(l.credit or 0)) for l in legs)
        self.assertEqual(debits, credits, "the discrepancy entry does not balance")
        self.assertEqual(debits, Decimal("40.000"))

    def test_a_shortfall_debits_the_expense_and_credits_the_bank(self):
        """Statement below the ticked lines: the books lose cash."""
        recon = self.reconciliation(statement_ending=Decimal("60"))
        txn = self.txn(received=Decimal("100"))  # difference = -40

        serializer = self.finish(recon, [txn], force=True, forced_reason="fee")
        serializer.is_valid(raise_exception=True)
        serializer.save()

        entry = JournalEntry.objects.get(kind=JournalEntryKindChoices.BANK_RECONCILIATION)
        by_account = {
            c.account.system_key or c.account.title: c
            for c in JournalEntryConnector.objects.filter(journal=entry)
        }
        self.assertEqual(
            by_account["Acme Operating"].kind, JournalEntryConnectorKindChoices.CREDIT
        )
        self.assertEqual(
            by_account[
                ChartOfAccountSystemKeyChoices.RECONCILIATION_DISCREPANCIES
            ].kind,
            JournalEntryConnectorKindChoices.DEBIT,
        )

    def test_a_surplus_debits_the_bank(self):
        """The mirror. Both sides come from the account kind, not a literal."""
        recon = self.reconciliation(statement_ending=Decimal("100"))
        txn = self.txn(received=Decimal("60"))  # difference = +40

        serializer = self.finish(recon, [txn], force=True, forced_reason="fee")
        serializer.is_valid(raise_exception=True)
        serializer.save()

        entry = JournalEntry.objects.get(kind=JournalEntryKindChoices.BANK_RECONCILIATION)
        bank_leg = JournalEntryConnector.objects.get(journal=entry, account=self.bank)
        self.assertEqual(bank_leg.kind, JournalEntryConnectorKindChoices.DEBIT)

    # ---------------------------------------------- the discrepancy account

    def test_the_account_is_created_on_first_force_and_reused_after(self):
        key = ChartOfAccountSystemKeyChoices.RECONCILIATION_DISCREPANCIES
        self.assertFalse(
            ChartOfAccount.objects.filter(
                company=self.company, system_key=key
            ).exists(),
            "should not exist until a session is actually forced",
        )

        for statement, on in (
            (Decimal("100"), date(2026, 8, 1)),
            (Decimal("200"), date(2026, 9, 1)),
        ):
            recon = self.reconciliation(statement_ending=statement, on=on)
            serializer = self.finish(
                recon, [self.txn(received=Decimal("10"))],
                force=True, forced_reason="fee",
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        self.assertEqual(
            ChartOfAccount.objects.filter(
                company=self.company, system_key=key
            ).count(),
            1,
            "a second forced close made a second account",
        )

    def test_the_account_is_protected(self):
        recon = self.reconciliation(statement_ending=Decimal("100"))
        serializer = self.finish(
            recon, [self.txn(received=Decimal("60"))],
            force=True, forced_reason="fee",
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        account = ChartOfAccount.objects.get(
            company=self.company,
            system_key=ChartOfAccountSystemKeyChoices.RECONCILIATION_DISCREPANCIES,
        )
        self.assertTrue(account.is_fixed, "the ledger posts here; it must not be edited")
        self.assertEqual(account.kind, ChartOfAccountKindChoices.EXPENSES)
        self.assertEqual(account.code, "8590")

    # -------------------------------------------------------------- reopen

    def test_an_already_closed_session_cannot_be_closed_again(self):
        recon = self.reconciliation(statement_ending=Decimal("100"))
        serializer = self.finish(recon, [self.txn(received=Decimal("100"))])
        serializer.is_valid(raise_exception=True)
        serializer.save()

        again = self.finish(recon, [self.txn(received=Decimal("5"))])
        self.assertFalse(again.is_valid())


class SharedDifferenceTests(TestCase):
    """The summary and the close must read one expression, not two."""

    def test_the_summary_view_uses_the_shared_helper(self):
        import inspect

        from weapi.django_rest.views.transactions import bank_reconcile

        source = inspect.getsource(
            bank_reconcile.PrivateWeBankReconciliationSummaryView
        )
        self.assertIn("reconciliation_difference(reconciliation)", source)
        self.assertNotIn("statement_ending_balance - (", source)

    def test_the_close_path_checks_the_difference(self):
        import inspect

        from weapi.django_rest.serializers.transactions import bank_reconcile

        source = inspect.getsource(
            bank_reconcile.PrivateWeTransactionMatchSerializer
        )
        self.assertIn("reconciliation_difference(", source)
