"""The write-time balance check on `create_journal_entry_connector`.

Production held 307 unbalanced journal entries across 12 companies before
anything looked. `create_journal_entry_connector` is the one function all five
posting implementations pass through, and it compared nothing.
"""

import logging

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import JournalEntryKindChoices
from journalio.django_rest.services.journals import (
    JournalEntryService,
    assert_entry_balances,
)
from journalio.models import JournalEntry


class BalanceGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.bank = ChartOfAccount.objects.create(
            title="City Bank", code="1000", company=cls.company,
            kind=ChartOfAccountKindChoices.ASSETS,
        )
        cls.income = ChartOfAccount.objects.create(
            title="Sales of Product Income", code="4000", company=cls.company,
            kind=ChartOfAccountKindChoices.INCOMES,
        )

    def entry(self):
        return JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.SALE
        )

    def post(self, entry, connector_data):
        return JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data, total=0, journal_entry=entry
        )

    def test_a_balanced_entry_logs_nothing(self):
        entry = self.entry()
        # "addition" is DEBIT on an asset and CREDIT on income, so this is
        # 100 debit against 100 credit.
        with self.assertNoLogs("journalio", level=logging.ERROR):
            self.post(entry, [
                (self.bank, "addition", 100, 0, None),
                (self.income, "addition", 100, 0, None),
            ])

    def test_an_unbalanced_entry_is_reported(self):
        entry = self.entry()

        with self.assertLogs("journalio", level=logging.ERROR) as captured:
            self.post(entry, [(self.income, "addition", 550, 0, None)])

        message = "\n".join(captured.output)
        self.assertIn("does NOT balance", message)
        self.assertIn(str(entry.pk), message)
        self.assertIn("550", message)

    def test_the_entry_is_still_written(self):
        """Logs, does not raise -- document kinds are still posting badly.

        Raising today would turn each of those into a 500 on a request that
        currently succeeds, before the fixes that would prevent it have landed.
        """
        entry = self.entry()

        with self.assertLogs("journalio", level=logging.ERROR):
            result = self.post(entry, [(self.income, "addition", 550, 0, None)])

        self.assertTrue(result)
        self.assertEqual(entry.journalentryconnector_set.count(), 1)

    def test_two_legs_on_the_same_side_are_caught(self):
        """The shape four of company 165's opening-balance entries have.

        Both legs credited, so the entry is out by exactly twice the amount --
        `addition` is CREDIT for both INCOMES and LIABILITIES, and a caller
        hard-coding it for a pair that should straddle the ledger gets this.
        """
        liability = ChartOfAccount.objects.create(
            title="Import - Loan Payable", code="2000", company=self.company,
            kind=ChartOfAccountKindChoices.LIABILITIES,
        )
        entry = self.entry()

        with self.assertLogs("journalio", level=logging.ERROR) as captured:
            self.post(entry, [
                (self.income, "addition", 20869, 0, None),
                (liability, "addition", 20869, 0, None),
            ])

        self.assertIn("out by -41738", "\n".join(captured.output))

    def test_it_reads_the_whole_entry_not_just_this_batch(self):
        """A few callers build one entry across more than one call.

        Checking only the rows just written would report the first half of
        every such entry as broken.
        """
        entry = self.entry()

        with self.assertLogs("journalio", level=logging.ERROR):
            self.post(entry, [(self.bank, "addition", 100, 0, None)])

        # Second call completes it; the entry as a whole now balances.
        with self.assertNoLogs("journalio", level=logging.ERROR):
            self.post(entry, [(self.income, "addition", 100, 0, None)])

    def test_helper_is_safe_on_a_missing_entry(self):
        self.assertTrue(assert_entry_balances(None))
