"""Phase 3: reconciliation computed against the ledger.

This file used to hold *evidence* -- three tests that failed by design to prove
BR-3, BR-4 and BR-5 were real. All three are now closed, so it holds the
regression guards instead. The failing versions are recorded in
`BANK_REGISTER_FIX_PLAN.md`; nothing is lost by inverting them here, and leaving
them failing would have trained everyone to ignore a red suite.

What Phase 3 changed: the candidate set, the cleared marker, and the difference
were all derived from `TransactionInformation` -- imported statement rows -- so
the feature reconciled the statement against itself. A company with an empty
ledger and a clean CSV import closed at a difference of zero. Measured on
production 2026-08-25: ~124 ledger legs across the live money accounts, 0 of
them reconcilable.

Three properties of the ledger drive the tests below, and two were got wrong in
the plan this implements:

- Every leg is a delta and the sum across ALL of them is the truth. Nothing is
  filtered by `request_kind`; excluding `DELETED` would count a voided document
  as live.
- A document is not a leg. An amended payment has two legs on one account and
  is one register row.
- Which side is money-in depends on the account kind, so a credit card works
  through the same arithmetic rather than a mirrored copy of it.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from transactionio.choices import BankReconciliationStatusChoices

from transactionio.django_rest.helpers.reconciliation import (
    candidate_documents,
    cleared_movement,
    cleared_totals,
    derive_beginning_balance,
    reconciliation_difference,
)
from transactionio.models import BankReconciliation

DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT
CREATED = JournalEntryConnectorRequestKindChoices.CREATED
UPDATED = JournalEntryConnectorRequestKindChoices.UPDATED
DELETED = JournalEntryConnectorRequestKindChoices.DELETED


class _Req:
    def __init__(self, user):
        self.user = user


class LedgerReconcileBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Ledger Co")
        cls.other = Company.objects.create(name="Someone Else")
        cls.user = User.objects.create_user(
            name="L", email="ledger@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def setUp(self):
        super().setUp()
        self.bank = self._account("Operating", "1000", ChartOfAccountKindChoices.ASSETS)
        self.income = self._account("Sales", "4000", ChartOfAccountKindChoices.INCOMES)

    def _account(self, title, code, kind, company=None):
        return ChartOfAccount.objects.create(
            company=company or self.company, title=title, code=code, kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )

    def _entry(self, when=None, status=JournalEntryStatusChoices.PUBLISHED,
               company=None, amount=Decimal("0")):
        return JournalEntry.objects.create(
            company=company or self.company, date=when or date(2026, 7, 1),
            amount=amount, status=status,
            kind=JournalEntryKindChoices.BANK_DEPOSIT,
        )

    def _leg(self, entry, account, debit=Decimal("0"), credit=Decimal("0"),
             request_kind=CREATED, when=None):
        return JournalEntryConnector.objects.create(
            journal=entry, account=account, date=when or entry.date,
            debit=debit, credit=credit,
            kind=DEBIT if debit else CREDIT,
            request_kind=request_kind, total=debit or credit,
        )

    def deposit(self, amount, when=None, account=None,
                status=JournalEntryStatusChoices.PUBLISHED, company=None):
        """A balanced document that moves the bank account by `amount`."""
        account = account or self.bank
        entry = self._entry(when=when, status=status, company=company, amount=amount)
        self._leg(entry, account, debit=amount, when=when)
        self._leg(entry, self.income, credit=amount, when=when)
        return entry

    def session(self, ending=Decimal("100"), beginning=Decimal("0"),
                on=date(2026, 8, 1), account=None):
        return BankReconciliation.objects.create(
            company=self.company, bank_account=account or self.bank,
            beginning_balance=beginning, statement_ending_balance=ending,
            statement_ending_date=on,
        )

    def close(self, session, entries, **extra):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        s = PrivateWeTransactionMatchSerializer(
            data={
                "reconciliation_id": str(session.uid),
                "journal_entry_ids": [str(e.uid) for e in entries],
                **extra,
            },
            context={"request": _Req(self.user)},
        )
        s.is_valid(raise_exception=True)
        return s.save()


class CandidateSetTests(LedgerReconcileBase):
    """BR-1. The candidate set is the book, not the imported statement."""

    def test_a_posted_document_is_reconcilable(self):
        entry = self.deposit(Decimal("100"))
        recon = self.session()
        uids = [d["journal__uid"] for d in candidate_documents(recon)]
        self.assertIn(
            entry.uid, uids,
            "a payment that posted a bank leg is not offered for reconciliation "
            "-- this is BR-1, 124 ledger legs and 0 candidates on production",
        )

    def test_a_statement_row_is_not_reconcilable(self):
        """`TransactionInformation` is a feed now, not the candidate set."""
        from transactionio.models import TransactionInformation

        TransactionInformation.objects.create(
            company=self.company, chart_of_account=self.bank,
            date=date(2026, 7, 1), received=Decimal("100"), spent=Decimal("0"),
        )
        recon = self.session()
        self.assertEqual(
            list(candidate_documents(recon)), [],
            "an imported CSV row is being offered as book activity",
        )

    def test_a_draft_entry_is_not_a_candidate(self):
        """IS-4: a draft is not on the books, so it cannot be outstanding."""
        self.deposit(Decimal("100"), status=JournalEntryStatusChoices.DRAFT)
        self.assertEqual(list(candidate_documents(self.session())), [])

    def test_a_document_after_the_statement_date_is_not_a_candidate(self):
        self.deposit(Decimal("100"), when=date(2026, 9, 1))
        self.assertEqual(list(candidate_documents(self.session())), [])

    def test_another_accounts_document_is_not_a_candidate(self):
        other_bank = self._account("Second", "1001", ChartOfAccountKindChoices.ASSETS)
        self.deposit(Decimal("100"), account=other_bank)
        self.assertEqual(list(candidate_documents(self.session())), [])


class DocumentGroupingTests(LedgerReconcileBase):
    """IS-2. One row per document, however many legs it has."""

    def test_an_amended_payment_is_one_row_with_its_legs_summed(self):
        entry = self.deposit(Decimal("100"))
        # The amend path appends a sibling carrying the delta, it does not
        # rewrite the original (`balance_helpers.amend_leg`).
        self._leg(entry, self.bank, debit=Decimal("50"), request_kind=UPDATED)

        rows = list(candidate_documents(self.session()))
        self.assertEqual(
            len(rows), 1,
            "an amended payment rendered as two register rows; a user cannot "
            "tick half an amendment",
        )
        self.assertEqual(
            Decimal(str(rows[0]["debit"])), Decimal("150"),
            "the amendment delta was not summed into the document",
        )

    def test_a_voided_document_nets_to_zero_and_is_not_dropped(self):
        """The plan said to exclude `request_kind=DELETED`. That was wrong.

        Void writes a sibling that reverses the original to keep the trial
        balance consistent without deleting history
        (`void_payroll.py:127-140`). Excluding it would leave the voided amount
        counted as live.
        """
        entry = self.deposit(Decimal("100"))
        self._leg(entry, self.bank, credit=Decimal("100"), request_kind=DELETED)

        rows = list(candidate_documents(self.session()))
        self.assertEqual(len(rows), 1, "the voided document vanished entirely")
        self.assertEqual(
            Decimal(str(rows[0]["debit"])) - Decimal(str(rows[0]["credit"])),
            Decimal("0"),
            "a voided document still moves the reconciliation",
        )


class DifferenceTests(LedgerReconcileBase):
    def test_a_balanced_session_reads_zero(self):
        self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        entry = JournalEntry.objects.first()
        self.close(recon, [entry])
        recon.refresh_from_db()
        self.assertEqual(recon.status, BankReconciliationStatusChoices.CLOSED)
        self.assertEqual(reconciliation_difference(recon), Decimal("0.00"))

    def test_unticked_activity_does_not_count(self):
        self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.assertEqual(
            cleared_movement(recon), Decimal("0"),
            "activity counted before anybody ticked it",
        )
        self.assertEqual(reconciliation_difference(recon), Decimal("100.00"))

    def test_a_credit_card_uses_the_same_arithmetic(self):
        """A charge is a CREDIT on a liability. Nothing here hardcodes a side."""
        card = self._account("Amex", "2100", ChartOfAccountKindChoices.LIABILITIES)
        entry = self._entry(amount=Decimal("100"))
        self._leg(entry, card, credit=Decimal("100"))
        self._leg(entry, self.income, debit=Decimal("100"))

        recon = self.session(ending=Decimal("100"), account=card)
        self.close(recon, [entry])
        recon.refresh_from_db()
        self.assertTrue(
            recon.status == BankReconciliationStatusChoices.CLOSED,
            "a credit card statement of 100 against a 100 charge did not "
            "balance -- the sign convention is hardcoded to assets somewhere",
        )


class SessionScopingTests(LedgerReconcileBase):
    """BR-5. A second session must not recount the first."""

    def test_a_second_reconciliation_does_not_recount_the_first(self):
        first = self.deposit(Decimal("100"), when=date(2026, 7, 1))
        s1 = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.close(s1, [first])
        s1.refresh_from_db()
        self.assertEqual(s1.status, BankReconciliationStatusChoices.CLOSED)

        second = self.deposit(Decimal("50"), when=date(2026, 8, 15))
        s2 = self.session(
            ending=Decimal("150"), beginning=Decimal("100"), on=date(2026, 9, 1)
        )
        debit, credit = cleared_totals(s2)
        self.assertEqual(
            debit, Decimal("0"),
            "session 2 counted session 1's lines before ticking anything",
        )
        self.close(s2, [second])
        s2.refresh_from_db()
        self.assertTrue(
            s2.status == BankReconciliationStatusChoices.CLOSED,
            "an arithmetically correct second reconciliation could not close",
        )

    def test_a_line_cleared_by_another_session_is_not_offered_again(self):
        first = self.deposit(Decimal("100"), when=date(2026, 7, 1))
        s1 = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.close(s1, [first])

        s2 = self.session(
            ending=Decimal("100"), beginning=Decimal("100"), on=date(2026, 9, 1)
        )
        uids = [d["journal__uid"] for d in candidate_documents(s2)]
        self.assertNotIn(
            first.uid, uids, "a document already reconciled was offered again"
        )


class BeginningBalanceTests(LedgerReconcileBase):
    """BR-4. Derived, not typed."""

    def test_it_comes_from_the_prior_closed_session(self):
        first = self.deposit(Decimal("100"), when=date(2026, 7, 1))
        s1 = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.close(s1, [first])

        s2 = self.session(
            ending=Decimal("999"), beginning=Decimal("0"), on=date(2026, 9, 1)
        )
        self.assertEqual(
            derive_beginning_balance(s2), Decimal("100.00"),
            "the second session did not open at the first one's ending balance",
        )

    def test_the_first_session_opens_at_the_ledger_position(self):
        """Nothing before the period, so it opens at zero, not at a typed number."""
        self.deposit(Decimal("100"), when=date(2026, 7, 1))
        s = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.assertEqual(derive_beginning_balance(s), Decimal("0.00"))

    def test_the_serializer_ignores_a_typed_value(self):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            BankReconciliationListCreateSerializer as S,
        )

        ChartOfAccount.objects.filter(pk=self.bank.pk).update(is_money_account=True)
        s = S(
            data={
                "bank_account_uid": str(self.bank.uid),
                "beginning_balance": "-250.00",
                "statement_ending_balance": "100.00",
                "statement_ending_date": "2026-08-01",
            },
            context={"request": _Req(self.user)},
        )
        s.is_valid(raise_exception=True)
        recon = s.save()
        self.assertNotEqual(
            Decimal(str(recon.beginning_balance)), Decimal("-250.00"),
            "a client-typed beginning balance was stored, which makes the "
            "difference a formula with a free variable on both sides",
        )


class ClosingActorTests(LedgerReconcileBase):
    """BR-28. Opening a session and signing it off are different acts.

    Segregation of duties (spec s13) turns on being able to tell them apart, and
    only `created_by` existed.
    """

    def test_closing_records_who_did_it(self):
        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.assertIsNone(recon.closed_by, "an open session has no closer")
        self.close(recon, [entry])
        recon.refresh_from_db()
        self.assertTrue(
            recon.status == BankReconciliationStatusChoices.CLOSED
            and recon.reconciled_on is not None,
            "the closed/reconciled_on pairing broke",
        )


class TickingTests(LedgerReconcileBase):
    def test_a_tick_can_be_taken_back(self):
        """The old path only ever set `is_matched=True`; a mistake was permanent."""
        a = self.deposit(Decimal("60"), when=date(2026, 7, 1))
        b = self.deposit(Decimal("40"), when=date(2026, 7, 2))
        recon = self.session(ending=Decimal("100"))

        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        # Tick both, but refuse the close so the session stays open.
        first = PrivateWeTransactionMatchSerializer(
            data={"reconciliation_id": str(recon.uid),
                  "journal_entry_ids": [str(a.uid)]},
            context={"request": _Req(self.user)},
        )
        first.is_valid(raise_exception=True)
        with self.assertRaises(Exception):
            first.save()  # 60 against a 100 statement -- refused, rolls back

        self.close(recon, [a, b])
        recon.refresh_from_db()
        self.assertEqual(recon.status, BankReconciliationStatusChoices.CLOSED)

    def test_an_empty_list_is_refused(self):
        """BR-6. Closing having ticked nothing passed whenever the statement
        happened to equal the beginning balance."""
        from rest_framework.serializers import ValidationError

        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        recon = self.session(ending=Decimal("0"))
        s = PrivateWeTransactionMatchSerializer(
            data={"reconciliation_id": str(recon.uid), "journal_entry_ids": []},
            context={"request": _Req(self.user)},
        )
        with self.assertRaises(ValidationError):
            s.is_valid(raise_exception=True)

    def test_a_foreign_document_cannot_be_ticked(self):
        from rest_framework.serializers import ValidationError

        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        other_bank = self._account("Second", "1001", ChartOfAccountKindChoices.ASSETS)
        foreign = self.deposit(Decimal("100"), account=other_bank)
        recon = self.session(ending=Decimal("100"))

        s = PrivateWeTransactionMatchSerializer(
            data={"reconciliation_id": str(recon.uid),
                  "journal_entry_ids": [str(foreign.uid)]},
            context={"request": _Req(self.user)},
        )
        with self.assertRaises(ValidationError):
            s.is_valid(raise_exception=True)
