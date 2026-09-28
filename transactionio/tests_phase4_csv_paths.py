"""Phase 4: the statement-import paths. BR-18 through BR-22.

`PATCH /csv/update` categorises imported feed lines into journal entries, and
undoes that. Phase 3 re-scoped `TransactionInformation` from "the reconciliation
candidate set" to "a statement feed", which is what it always was -- so this
path is still live and still the only writer of that table.

Each test drives `UpsertCSVTransactionsSerializer.update()` with input a client
can actually send.
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

from transactionio.choices import TransactionStatusChoices
from transactionio.models import TransactionInformation


class CsvPathBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="CSV Co")
        cls.other = Company.objects.create(name="Someone Else")
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="Operating", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )

    def line(self, company=None, **extra):
        fields = dict(
            company=company or self.company, chart_of_account=self.bank,
            date=date(2026, 7, 1), description="ACME PAYMENT",
            received=Decimal("100"), spent=Decimal("0"),
        )
        fields.update(extra)
        return TransactionInformation.objects.create(**fields)

    def entry_for(self, line):
        """A categorisation: the journal entry this feed line produced."""
        entry = JournalEntry.objects.create(
            company=self.company, date=date(2026, 7, 1), amount=Decimal("100"),
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.BANK_DEPOSIT,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=self.bank, date=entry.date,
            debit=Decimal("100"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            total=Decimal("100"),
        )
        TransactionInformation.objects.filter(pk=line.pk).update(journal_entry=entry)
        line.refresh_from_db()
        return entry

    def run_update(self, rows, undo=True):
        from weapi.django_rest.serializers.transactions.csv_transactions import (
            UpsertCSVTransactionsSerializer,
        )

        s = UpsertCSVTransactionsSerializer(context={"company": self.company})
        return s.update(
            None,
            {"transactions": rows, "undo": undo, "chart_of_account": self.bank},
        )


class UndoCrashTests(CsvPathBase):
    """BR-21. Four ways a client can turn this endpoint into a 500."""

    def test_an_unknown_uid_does_not_crash(self):
        """`.first()` returns None and the next line dereferences it."""
        import uuid

        self.run_update([{"uid": str(uuid.uuid4()), "description": "x"}])

    def test_another_companys_uid_does_not_crash(self):
        """Same shape, reached through the company filter rather than a typo."""
        foreign = self.line(company=self.other)
        self.run_update([{"uid": str(foreign.uid), "description": "x"}])

    def test_an_empty_transaction_list_does_not_crash(self):
        """`trx_data[0]` indexes a list the client controls."""
        self.run_update([])

    def test_a_row_of_only_uid_does_not_crash(self):
        """`bulk_update(fields=[])` raises -- and uid-only is the natural undo."""
        line = self.line()
        self.run_update([{"uid": str(line.uid)}])


class UndoPersistenceTests(CsvPathBase):
    """BR-19. The undo assigns three fields and persists none of them."""

    def test_undo_resets_the_status(self):
        line = self.line(transaction_status=TransactionStatusChoices.CATEGORIZED)
        self.entry_for(line)

        self.run_update([{"uid": str(line.uid), "description": "x"}])

        line.refresh_from_db()
        self.assertEqual(
            line.transaction_status, TransactionStatusChoices.FOR_REVIEW,
            "undo set transaction_status in memory and never wrote it -- "
            "`bulk_update` derives its column list from the client payload, and "
            "the field is read-only so it is never in the payload",
        )

    def test_undo_clears_the_journal_entry_link(self):
        line = self.line()
        self.entry_for(line)
        self.run_update([{"uid": str(line.uid), "description": "x"}])
        line.refresh_from_db()
        self.assertIsNone(line.journal_entry, "the categorisation link survived undo")

    def test_undo_takes_the_journal_entry_off_the_books(self):
        """Off the books, not out of the database.

        This asserted physical deletion until 2026-09-02, and the undo did
        `je_trx.delete()` to satisfy it. That is defect §1 of
        `LEDGER_WRITE_PATH_GAPS` -- erasing the rows leaves the stored balances
        asserting figures no ledger line supports, and nothing survives to
        measure the drift against or to explain what happened.

        The intent behind the old assertion is kept exactly: nothing the
        categorisation posted may still count. The entry is retired and a
        compensating reversal is posted, so the pair nets to zero on both
        readings of the ledger and the register (which filters
        `journal__status=PUBLISHED`) shows neither.
        """
        from journalio.choices import JournalEntryStatusChoices

        line = self.line()
        entry = self.entry_for(line)

        self.run_update([{"uid": str(line.uid), "description": "x"}])

        entry.refresh_from_db()
        self.assertEqual(
            entry.status, JournalEntryStatusChoices.REMOVED,
            "the entry the categorisation posted is still on the books",
        )
        self.assertFalse(
            JournalEntryConnector.objects.filter(
                journal__status=JournalEntryStatusChoices.PUBLISHED,
                journal__pk=entry.pk,
            ).exists(),
            "a published leg survived the undo",
        )

    # The balance half is covered properly in
    # `transactionio/tests_csv_undo_direction.py`, across all ten
    # kind x side combinations. It needs the posting to have moved the
    # balances first, which this file's fixture deliberately does not do -- it
    # builds entry rows directly to exercise the CSV paths, not the ledger.


class ColumnSetTests(CsvPathBase):
    """BR-20. The column list comes from row 0 and is applied to every row."""

    def test_a_later_rows_own_fields_are_written(self):
        first = self.line(description="FIRST")
        second = self.line(description="SECOND", payee="OLD PAYEE")

        self.run_update(
            [
                {"uid": str(first.uid), "description": "FIRST EDITED"},
                {"uid": str(second.uid), "payee": "NEW PAYEE"},
            ],
            undo=False,
        )

        second.refresh_from_db()
        self.assertEqual(
            second.payee, "NEW PAYEE",
            "row 1's `payee` was dropped because row 0 did not carry that key "
            "-- the column list is derived from the first row only",
        )


class AmountIntegrityTests(CsvPathBase):
    """BR-18 and BR-30. The two amount columns on a statement line.

    A statement line is money in or money out. Nothing said so: `received` and
    `spent` were independent, unvalidated and unconstrained, so a row could
    carry both, or carry a negative, and `cleared_totals` summed whatever was
    there.

    BR-30 is the same two lines: they were `(10, 2)` while every figure they
    feed -- `beginning_balance`, `statement_ending_balance`, the ledger's
    `debit`/`credit` -- is `(19, 3)` or `(19, 2)`. The same computation was
    carried at two precisions, and the narrower one silently capped at
    99,999,999.99.
    """

    def assert_refused(self, **amounts):
        from django.db import IntegrityError, transaction as db_transaction

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                self.line(**amounts)

    def test_a_negative_receipt_is_refused(self):
        self.assert_refused(received=Decimal("-1"), spent=Decimal("0"))

    def test_a_negative_payment_is_refused(self):
        self.assert_refused(received=Decimal("0"), spent=Decimal("-1"))

    def test_a_line_that_is_both_a_receipt_and_a_payment_is_refused(self):
        self.assert_refused(received=Decimal("100"), spent=Decimal("50"))

    def test_the_ordinary_shapes_are_allowed(self):
        self.line(received=Decimal("100"), spent=Decimal("0"))
        self.line(received=Decimal("0"), spent=Decimal("100"))
        self.line(received=None, spent=None)

    def test_the_columns_carry_the_same_range_as_the_figures_they_feed(self):
        """BR-30. A statement line must not cap below the balance it explains."""
        received = TransactionInformation._meta.get_field("received")
        beginning = None
        from transactionio.models import BankReconciliation

        beginning = BankReconciliation._meta.get_field("beginning_balance")
        self.assertGreaterEqual(
            received.max_digits, beginning.max_digits,
            f"a statement line caps at {received.max_digits} digits while the "
            f"balance it feeds carries {beginning.max_digits}",
        )


class AmountSerializerMessageTests(CsvPathBase):
    """The database is the guarantee; this is the message.

    An import of a thousand rows should say which row is wrong, not surface an
    IntegrityError as a 500.
    """

    def _wrapper(self, **amounts):
        from weapi.django_rest.serializers.transactions.csv_transactions import (
            TransactionWrapperSerializer,
        )

        payload = {"date": "2026-07-01", "description": "X"}
        payload.update(amounts)
        return TransactionWrapperSerializer(data=payload)

    def test_a_negative_receipt_names_the_field(self):
        s = self._wrapper(received="-1", spent="0")
        self.assertFalse(s.is_valid())
        self.assertIn("received", s.errors)

    def test_both_sides_is_refused_with_both_figures(self):
        s = self._wrapper(received="100", spent="50")
        self.assertFalse(s.is_valid())
        self.assertIn("100", str(s.errors))
        self.assertIn("50", str(s.errors))

    def test_an_ordinary_row_still_validates(self):
        self.assertTrue(self._wrapper(received="100", spent="0").is_valid())

    def test_a_row_omitting_amounts_still_validates(self):
        """Partial updates must not be forced to restate amounts."""
        self.assertTrue(self._wrapper().is_valid())
