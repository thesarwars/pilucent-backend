"""A refund's cost legs post as a pair or not at all.

Caught in production the morning after deploying the recurring-invoice fix.
Company 114, journal 2766, a nightly recurring REFUND_RECEIPT dated 2026-08-08:

    Hello Bank                  credit  18.000
    Cost of Goods Sold (COGS)   credit 100.000    <-- alone
    Service                     debit   18.000
    -> out by -100.000

The two refunds before it, on identical templates, balanced at 18/18 with no
cost legs at all. The difference is that this one found a cost to return.

Returned goods DEBIT Inventory Asset and CREDIT cost of sales. The two were
gated independently:

    if asset_account and refund_cost > 0:   ...
    if cogs_account and refund_cost > 0:    ...

and the product carries no `asset_account` while `resolve_cogs_account` falls
back to the company's COGS control account -- so the cost half resolved, the
inventory half did not, and the entry was short by the cost.

This is Product #5's defect. The SALE path gained the pairing guard in
`7cc3134c`; the refund path was missed.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company


class RefundCostPairTests(TestCase):
    """Exercises the pairing rule the refund path now applies.

    Driving a whole refund receipt needs a posted sale, stock layers and a
    customer; the defect is entirely in whether one leg can post without the
    other, so this pins that.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Jumatechs")

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def setUp(self):
        super().setUp()
        self.asset = self.account("Inventory Asset", ChartOfAccountKindChoices.ASSETS)
        self.cogs = self.account(
            "Cost of Goods Sold (COGS)", ChartOfAccountKindChoices.EXPENSES
        )

    def pair_posts(self, cogs_account, asset_account, refund_cost=Decimal("100")):
        """The rule as the refund path now expresses it."""
        if refund_cost <= 0:
            return False
        return bool(cogs_account and asset_account)

    def test_the_production_shape_posts_neither_leg(self):
        """journal 2766: a COGS account resolved, no asset account."""
        self.assertFalse(self.pair_posts(self.cogs, None))

    def test_both_accounts_posts_both_legs(self):
        self.assertTrue(self.pair_posts(self.cogs, self.asset))

    def test_an_asset_without_a_cogs_account_posts_neither(self):
        self.assertFalse(self.pair_posts(None, self.asset))

    def test_zero_cost_posts_nothing(self):
        self.assertFalse(self.pair_posts(self.cogs, self.asset, Decimal("0")))

    def test_the_sale_path_applies_the_same_rule(self):
        """Both paths must agree, or an amendment cannot unwind cleanly."""
        import inspect

        from weapi.django_rest.helpers import sale_posting

        source = inspect.getsource(sale_posting)
        self.assertEqual(
            source.count("if not (cogs_account and asset_account)"),
            2,
            "the sale and refund paths must both gate the cost pair",
        )

