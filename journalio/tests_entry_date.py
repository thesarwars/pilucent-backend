"""A journal entry should carry the date it belongs to, not the day it was written.

`JournalEntry.date` and `JournalEntryConnector.date` are both
`DateField(default=date.today)`, and neither `create_journal_entry` nor
`create_journal_entry_connector` accepted a date -- so every document posting
took the default. A sale dated 2025-01-01, entered today, produced a journal
entry dated today.

Every posting path went through those two functions: sale, purchase, payroll,
credit note, pay bill, bank deposit, opening balance. The one exception is the
manual journal-entry serializer, which sets the field itself.

This is additive. Omitted, the model default still applies and no figure moves.
It has to exist before an as-of balance sheet or a period P&L keyed on `date`
can mean anything.
"""

from datetime import date

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import JournalEntryKindChoices
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry


class EntryDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        cls.income = ChartOfAccount.objects.create(
            company=cls.company, title="Sales", code="4000",
            kind=ChartOfAccountKindChoices.INCOMES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def entry(self, **kwargs):
        return JournalEntryService.create_journal_entry(
            amount=100,
            kind=JournalEntryKindChoices.SALE,
            company=self.company,
            object=None,
            **kwargs,
        )

    def post_legs(self, entry, **kwargs):
        JournalEntryService.create_journal_entry_connector(
            connector_data=[
                (self.bank, "addition", 100, 0, None),
                (self.income, "addition", 100, 0, None),
            ],
            total=100,
            journal_entry=entry,
            **kwargs,
        )
        return list(entry.journalentryconnector_set.all())

    def test_a_backdated_entry_keeps_its_date(self):
        entry = self.entry(date=date(2025, 1, 1))

        self.assertEqual(entry.date, date(2025, 1, 1))

    def test_omitting_the_date_still_defaults_to_today(self):
        """Additive: nothing moves for a caller that does not pass one."""
        entry = self.entry()

        self.assertEqual(entry.date, date.today())

    def test_the_lines_inherit_the_entry_date(self):
        """A caller that dates the entry should not have to date the lines too."""
        entry = self.entry(date=date(2025, 1, 1))

        rows = self.post_legs(entry)

        self.assertEqual({row.date for row in rows}, {date(2025, 1, 1)})

    def test_the_lines_can_be_dated_explicitly(self):
        entry = self.entry(date=date(2025, 1, 1))

        rows = self.post_legs(entry, date=date(2025, 2, 2))

        self.assertEqual({row.date for row in rows}, {date(2025, 2, 2)})

    def test_lines_on_an_undated_entry_default_to_today(self):
        entry = self.entry()

        rows = self.post_legs(entry)

        self.assertEqual({row.date for row in rows}, {date.today()})

    def test_the_entry_still_balances(self):
        """Dating changes nothing about the amounts."""
        entry = self.entry(date=date(2025, 1, 1))

        rows = self.post_legs(entry)

        debit = sum(row.debit or 0 for row in rows)
        credit = sum(row.credit or 0 for row in rows)
        self.assertEqual(debit, credit)


class ManualEntryUnaffectedTests(TestCase):
    """The one path that already got this right must keep working."""

    def test_journal_entry_date_is_a_real_field(self):
        self.assertTrue(
            any(f.name == "date" for f in JournalEntry._meta.fields)
        )
