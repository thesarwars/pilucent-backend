"""Tax a document declares but does not attribute must still be posted.

Production company 165, journal 2694, SALE_RECEPT, 2026-07-06:

    Metro Housing            LIABILITIES  credit     37.500
    City Bank                ASSETS       debit   8,090.625
    ... revenue 7,500, COGS/inventory pairs balanced ...
    -> out by +553.125

Revenue was 7,500 and the bank was debited 8,090.625, so 590.625 of tax was
collected -- but only 37.50 reached a liability account. The other 553.125 was
detected and discarded: `_post_unattributed_tax` returned as soon as any leg
had posted, logging a warning.

The reasoning for that (a plug entry would hide a header disagreeing with its
own detail) was right; the remedy was wrong. An unbalanced ledger is a worse
way to keep a fault visible than a balanced one plus a WARNING.
"""

import logging
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices

from weapi.django_rest.helpers.sale_posting import _post_unattributed_tax


class TaxResidualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.payable = ChartOfAccount.objects.create(
            company=cls.company, title="Sales Tax Payable", code="2200",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def sale(self, total_tax):
        return SimpleNamespace(
            pk=2694, company=self.company, company_id=self.company.pk,
            total_tax=Decimal(str(total_tax)),
        )

    def run_post(self, total_tax, posted):
        connector_data = []
        _post_unattributed_tax(
            self.sale(total_tax), Decimal(str(posted)),
            JournalEntryConnectorKindChoices.CREDIT, connector_data,
        )
        return connector_data

    def test_the_shortfall_is_posted(self):
        """The production case: 590.625 declared, 37.50 attributed."""
        connector_data = self.run_post("590.625", "37.500")

        self.assertEqual(len(connector_data), 1)
        account, action, amount, *_ = connector_data[0]
        self.assertEqual(account, self.payable)
        self.assertEqual(action, "addition")
        self.assertEqual(amount, Decimal("553.13"),
                         "the residual is quantized to match its counter-legs")

    def test_the_disagreement_is_still_reported(self):
        """Balancing the entry must not silence the fault."""
        with self.assertLogs("weapi", level=logging.WARNING) as captured:
            self.run_post("590.625", "37.500")

        self.assertIn("disagrees with its own detail", "\n".join(captured.output))

    def test_a_fully_unattributed_total_still_posts_in_full(self):
        """The case the function already handled -- must not regress."""
        connector_data = self.run_post("100.000", "0")

        self.assertEqual(len(connector_data), 1)
        self.assertEqual(connector_data[0][2], Decimal("100.000"))

    def test_legs_that_match_the_header_post_nothing(self):
        self.assertEqual(self.run_post("100.000", "100.000"), [])

    def test_rounding_noise_is_not_a_shortfall(self):
        """A cent of drift across per-line rates is not a missing leg."""
        self.assertEqual(self.run_post("100.000", "99.995"), [])

    def test_it_never_posts_a_negative_leg(self):
        """Legs totalling MORE than the header is a different fault.

        A negative-amount connector would be worse than the imbalance, so this
        reports and leaves the entry short rather than inventing one.
        """
        with self.assertLogs("weapi", level=logging.ERROR) as captured:
            connector_data = self.run_post("37.500", "590.625")

        self.assertEqual(connector_data, [])
        self.assertIn("Refusing to post a negative leg", "\n".join(captured.output))

    def test_a_refund_reverses_the_shortfall(self):
        """On a refund the direction flips, and the residual must follow it."""
        connector_data = []
        _post_unattributed_tax(
            self.sale("590.625"), Decimal("37.500"),
            JournalEntryConnectorKindChoices.DEBIT, connector_data,
        )

        self.assertEqual(len(connector_data), 1)
        self.assertEqual(connector_data[0][1], "substraction")
        self.assertEqual(connector_data[0][2], Decimal("553.13"),
                         "the residual is quantized to match its counter-legs")

    def test_no_payable_account_reports_rather_than_guessing(self):
        self.payable.delete()

        with self.assertLogs("weapi", level=logging.ERROR) as captured:
            connector_data = self.run_post("590.625", "37.500")

        self.assertEqual(connector_data, [])
        self.assertIn("no Sales Tax Payable account", "\n".join(captured.output))
