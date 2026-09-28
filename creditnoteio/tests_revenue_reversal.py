"""A credit note's revenue reversal must not depend on the line's cost.

Production company 114, two near-identical credit notes on the same day:

    journal 1439, out by -0.003:
        Minnesota State           LIABILITIES  debit    37.810
        County Transit            LIABILITIES  debit     2.750
        Accounts Receivable       ASSETS       credit  590.563
        Inventory Shrinkage       EXPENSES     credit  600.000
        Inventory Asset           ASSETS       debit   600.000
        Sales of Product Income   INCOMES      debit   550.000

    journal 1434, out by -550.003:
        Minnesota State           LIABILITIES  debit    37.810
        County Transit            LIABILITIES  debit     2.750
        Accounts Receivable       ASSETS       credit  590.563
        -- and nothing else.

The difference is the line's cost. `if total_cost_of_good != 0:` wrapped three
appends: the revenue reversal, the inventory restore and the COGS reversal. The
last two are a cost pair and belong under that gate; the revenue reversal is
sized by the line's INCOME and does not. So a line whose cost resolved to zero
credited the receivable back and never debited the revenue.

The balance moves also sat above the gate, so on those documents the income
account's stored balance moved by 550 while the journal recorded nothing.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from weapi.django_rest.serializers.creditnotes import append_product_reversal_legs


class RevenueReversalGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def setUp(self):
        super().setUp()
        self.income = self.account(
            "Sales of Product Income", ChartOfAccountKindChoices.INCOMES
        )
        self.asset = self.account(
            "Inventory Asset", ChartOfAccountKindChoices.ASSETS
        )
        self.cogs = self.account(
            "Inventory Shrinkage", ChartOfAccountKindChoices.EXPENSES
        )

    def legs(self, total_income, total_cost, **overrides):
        connector_data = []
        append_product_reversal_legs(
            connector_data,
            income_account=overrides.get("income_account", self.income),
            asset_account=overrides.get("asset_account", self.asset),
            cogs_account=overrides.get("cogs_account", self.cogs),
            total_income=Decimal(str(total_income)),
            total_cost=Decimal(str(total_cost)),
            item=None,
        )
        return {row[0].title: (row[1], row[2]) for row in connector_data}

    def test_zero_cost_still_reverses_revenue(self):
        """Journal 1434's shape: revenue 550, no cost."""
        rows = self.legs("550", "0")

        self.assertEqual(rows["Sales of Product Income"], ("substraction", Decimal("550")))
        self.assertNotIn("Inventory Asset", rows)
        self.assertNotIn("Inventory Shrinkage", rows)

    def test_the_cost_pair_posts_together_with_revenue(self):
        """Journal 1439's shape: revenue 550 and cost 600."""
        rows = self.legs("550", "600")

        self.assertEqual(rows["Sales of Product Income"][1], Decimal("550"))
        self.assertEqual(rows["Inventory Asset"], ("addition", Decimal("600")))
        self.assertEqual(rows["Inventory Shrinkage"], ("substraction", Decimal("600")))

    def test_a_zero_income_line_posts_no_revenue_leg(self):
        rows = self.legs("0", "600")

        self.assertNotIn("Sales of Product Income", rows)
        self.assertEqual(rows["Inventory Asset"][1], Decimal("600"))

    def test_the_income_balance_moves_only_with_its_connector(self):
        """The other half of the defect.

        The balance moves used to sit above the gate, so a zero-cost line moved
        the income account by its revenue while writing no journal line.
        """
        before = Decimal(str(self.income.opening_balance))

        self.legs("0", "600")

        self.income.refresh_from_db()
        self.assertEqual(Decimal(str(self.income.opening_balance)), before)

    def test_the_cost_balances_move_only_with_their_connectors(self):
        asset_before = Decimal(str(self.asset.opening_balance))
        cogs_before = Decimal(str(self.cogs.opening_balance))

        self.legs("550", "0")

        self.asset.refresh_from_db()
        self.cogs.refresh_from_db()
        self.assertEqual(Decimal(str(self.asset.opening_balance)), asset_before)
        self.assertEqual(Decimal(str(self.cogs.opening_balance)), cogs_before)

    def test_a_missing_account_is_skipped_not_crashed(self):
        """The item-level path guards each account; the helper must too."""
        rows = self.legs("550", "600", income_account=None, cogs_account=None)

        self.assertNotIn("Sales of Product Income", rows)
        self.assertNotIn("Inventory Shrinkage", rows)
        self.assertEqual(rows["Inventory Asset"][1], Decimal("600"))

    def test_the_income_balance_moves_when_it_does_post(self):
        before = Decimal(str(self.income.opening_balance))

        self.legs("550", "0")

        self.income.refresh_from_db()
        self.assertNotEqual(Decimal(str(self.income.opening_balance)), before)
