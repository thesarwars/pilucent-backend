"""Can a reconciliation be saved half-done?

Until `POST /reconcile/{uid}/lines` existed, it could not. `reconciliation` and
`cleared_on` were written in exactly two places -- closing a session and undoing
one -- and closing is atomic with ticking and refuses anything that does not
balance to zero. So a user who ticked forty lines and reloaded the page lost
forty ticks, and the only way to record any progress at all was to reconcile to
the penny in a single sitting.

The endpoint writes the same two columns the close path writes, so nothing new
has to interpret them: a line ticked against an OPEN session carries that
session's uid, which the register already renders as **C** -- reconciled means
pointing at a *closed* session.

Both actions are idempotent because this backs a checkbox. Only a document that
could not be ticked at all is refused.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from rest_framework.serializers import ValidationError

from transactionio.choices import BankReconciliationStatusChoices
from transactionio.models import BankReconciliation

from weapi.django_rest.serializers.transactions.bank_reconcile import (
    PrivateWeReconciliationLineTickSerializer,
)


class FakeRequest:
    def __init__(self, user):
        self.user = user


class LineTickTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="T", email="tick@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.bank = ChartOfAccount.objects.create(
            company=self.company, title="City Bank", code="BANK",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.session = self.make_session()

    def make_session(
        self,
        status=BankReconciliationStatusChoices.OPEN,
        statement_ending_date="2026-03-31",
        **extra,
    ):
        settled = status in (
            BankReconciliationStatusChoices.CLOSED,
            BankReconciliationStatusChoices.UNDONE,
        )
        undone = status == BankReconciliationStatusChoices.UNDONE
        return BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank, status=status,
            statement_ending_balance=Decimal("0"),
            beginning_balance=Decimal("0"),
            statement_ending_date=statement_ending_date,
            reconciled_on=statement_ending_date if settled else None,
            undone_on="2026-04-01" if undone else None,
            undo_reason="restated" if undone else "",
            **extra,
        )

    def document(self, amount="100", day="2026-03-01", legs=1):
        entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.SALE_PAYMENT_RECEIVE,
            status=JournalEntryStatusChoices.PUBLISHED,
        )
        for _ in range(legs):
            JournalEntryConnector.objects.create(
                journal=entry, account=self.bank, date=day,
                debit=Decimal(amount), credit=Decimal("0"),
                kind=JournalEntryConnectorKindChoices.DEBIT,
            )
        return entry

    def tick(self, uids, action="clear", session=None):
        serializer = PrivateWeReconciliationLineTickSerializer(
            data={"journal_uids": [str(u) for u in uids], "action": action},
            context={
                "request": FakeRequest(self.user),
                "uid": (session or self.session).uid,
            },
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def legs_of(self, entry):
        return JournalEntryConnector.objects.filter(journal=entry)


class TickingSavesProgressTests(LineTickTestCase):
    def test_a_ticked_document_is_recorded_without_closing(self):
        entry = self.document()

        result = self.tick([entry.uid])

        leg = self.legs_of(entry).get()
        self.assertEqual(leg.reconciliation_id, self.session.pk)
        self.assertIsNotNone(leg.cleared_on)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, BankReconciliationStatusChoices.OPEN)
        self.assertEqual(result["lines_changed"], 1)
        self.assertEqual(result["cleared_documents"], 1)

    def test_a_ticked_line_reads_as_cleared_not_reconciled(self):
        """The register's C state. R is a line on a *closed* session."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountSessionListSerializer,
        )

        entry = self.document()
        self.tick([entry.uid])

        leg = self.legs_of(entry).get()
        serializer = PrivateWeChartOfAccountSessionListSerializer(
            context={"account": self.bank}
        )
        self.assertEqual(serializer.get_reconciliation_status(leg), "C")

    def test_every_leg_of_a_document_moves_together(self):
        """An amended payment has a second leg; half a tick means nothing."""
        entry = self.document(legs=2)

        self.tick([entry.uid])

        self.assertEqual(
            self.legs_of(entry).filter(reconciliation=self.session).count(), 2
        )

    def test_unticking_releases_the_line_completely(self):
        entry = self.document()
        self.tick([entry.uid])

        self.tick([entry.uid], action="unclear")

        leg = self.legs_of(entry).get()
        self.assertIsNone(leg.reconciliation_id)
        self.assertIsNone(leg.cleared_on)

    def test_the_response_carries_the_difference_so_the_client_can_close(self):
        entry = self.document(amount="100")
        result = self.tick([entry.uid])
        # statement 0, beginning 0, one 100 debit ticked -> out by 100
        self.assertEqual(Decimal(result["difference"]), Decimal("-100"))


class IdempotencyTests(LineTickTestCase):
    """It backs a checkbox, so a double click must not be an error."""

    def test_clearing_twice_succeeds_and_changes_nothing_the_second_time(self):
        entry = self.document()
        self.tick([entry.uid])

        result = self.tick([entry.uid])

        self.assertEqual(result["lines_changed"], 0)
        self.assertEqual(result["cleared_documents"], 1)

    def test_a_re_tick_does_not_restamp_the_date(self):
        entry = self.document()
        self.tick([entry.uid])
        original = self.legs_of(entry).get().cleared_on

        self.tick([entry.uid])

        self.assertEqual(self.legs_of(entry).get().cleared_on, original)

    def test_unclearing_something_never_cleared_succeeds(self):
        entry = self.document()

        result = self.tick([entry.uid], action="unclear")

        self.assertEqual(result["lines_changed"], 0)
        self.assertEqual(result["cleared_documents"], 0)


class RefusalTests(LineTickTestCase):
    def test_a_document_on_another_account_is_refused_by_name(self):
        other = ChartOfAccount.objects.create(
            company=self.company, title="Other", code="OTH",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.SALE,
            status=JournalEntryStatusChoices.PUBLISHED,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=other, date="2026-03-01",
            debit=Decimal("10"), kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        with self.assertRaises(ValidationError) as caught:
            self.tick([entry.uid])
        self.assertIn(str(entry.uid), str(caught.exception))

    def test_a_document_after_the_statement_date_is_refused(self):
        entry = self.document(day="2026-04-15")
        with self.assertRaises(ValidationError):
            self.tick([entry.uid])

    def test_a_draft_document_is_refused(self):
        entry = self.document()
        JournalEntry.objects.filter(pk=entry.pk).update(
            status=JournalEntryStatusChoices.DRAFT
        )
        with self.assertRaises(ValidationError):
            self.tick([entry.uid])

    def test_a_document_cleared_by_another_session_is_refused(self):
        """`candidate_connectors` puts it in neither set -- it cannot be
        double-counted, and it cannot be stolen."""
        entry = self.document()
        # A different statement period: one live session per account per
        # period is a database constraint.
        other_session = self.make_session(
            status=BankReconciliationStatusChoices.OPEN,
            statement_ending_date="2026-04-30",
        )
        self.tick([entry.uid], session=other_session)

        with self.assertRaises(ValidationError):
            self.tick([entry.uid])

    def test_a_closed_session_cannot_be_ticked(self):
        entry = self.document()
        closed = self.make_session(
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_date="2026-02-28",
        )
        with self.assertRaises(ValidationError) as caught:
            self.tick([entry.uid], session=closed)
        self.assertIn("undo", str(caught.exception).lower())

    def test_an_undone_session_cannot_be_ticked(self):
        entry = self.document()
        undone = self.make_session(
            status=BankReconciliationStatusChoices.UNDONE,
            statement_ending_date="2026-01-31",
        )
        with self.assertRaises(ValidationError):
            self.tick([entry.uid], session=undone)

    def test_another_companys_session_is_not_found(self):
        theirs = Company.objects.create(name="Theirs", kind="ECOMMERCE")
        their_account = ChartOfAccount.objects.create(
            company=theirs, title="Their Bank", code="TB",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        their_session = BankReconciliation.objects.create(
            company=theirs, bank_account=their_account,
            status=BankReconciliationStatusChoices.OPEN,
            statement_ending_balance=Decimal("0"),
            beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31",
        )
        entry = self.document()
        with self.assertRaises(ValidationError) as caught:
            self.tick([entry.uid], session=their_session)
        self.assertIn("not found", str(caught.exception).lower())

    def test_an_empty_list_is_refused(self):
        serializer = PrivateWeReconciliationLineTickSerializer(
            data={"journal_uids": [], "action": "clear"},
            context={"request": FakeRequest(self.user), "uid": self.session.uid},
        )
        self.assertFalse(serializer.is_valid())

    def test_an_unknown_action_is_refused(self):
        entry = self.document()
        serializer = PrivateWeReconciliationLineTickSerializer(
            data={"journal_uids": [str(entry.uid)], "action": "maybe"},
            context={"request": FakeRequest(self.user), "uid": self.session.uid},
        )
        self.assertFalse(serializer.is_valid())


class ClosingStillWorksAfterTickingTests(LineTickTestCase):
    """The tick endpoint must not change what `/complete` means."""

    def test_a_session_ticked_here_can_still_be_closed(self):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        entry = self.document(amount="100")
        BankReconciliation.objects.filter(pk=self.session.pk).update(
            statement_ending_balance=Decimal("100")
        )
        self.session.refresh_from_db()
        self.tick([entry.uid])

        closer = PrivateWeTransactionMatchSerializer(
            data={
                "reconciliation_id": str(self.session.uid),
                "journal_entry_ids": [str(entry.uid)],
            },
            context={"request": FakeRequest(self.user)},
        )
        closer.is_valid(raise_exception=True)
        closer.save()

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, BankReconciliationStatusChoices.CLOSED)
        leg = self.legs_of(entry).get()
        self.assertEqual(leg.reconciliation_id, self.session.pk)
