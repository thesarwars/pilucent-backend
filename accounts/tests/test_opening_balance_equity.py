"""C1 — the Opening Balance Equity write, on account creation.

Two defects in the same three statements (`serializers/chart_of_accounts.py`):

**No None guard.** `get_chart_of_account` returns a dict, so `.get("Opening Balance
Equity")` yields `None` for a company without that account. The next line did
`None.opening_balance += …` — an `AttributeError`, so a **500 on ordinary account
creation** rather than a validation error the client can act on.

**An unlocked read-modify-write.** `obe.opening_balance += x` then
`save_dirty_fields()`. This is the single most contended balance in the schema — every
account creation in a company touches that one row — and it was the one doing a
read-modify-write. Two concurrent creations both read the same figure and write back their
own total, so one increment is lost. `update_opening_balance()` was given an `F()`
increment and a `refresh_from_db()` under P1.4 to close exactly this; this call site never
adopted it.

The accounting itself was correct and is unchanged: an opening balance on an ASSET is
funded by equity going up, and on a LIABILITY or EQUITY account by equity coming down.
That single difference was two near-identical branches; it is now one derived action.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    balance_operation_for_action,
    update_opening_balance,
)

from companyio.models import Company


class OpeningBalanceEquityWriteTests(TestCase):
    """The balance movement, exercised through the helper the fix now uses."""

    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def obe(self):
        return ChartOfAccount.objects.create(
            company=self.company,
            title="Opening Balance Equity",
            kind=ChartOfAccountKindChoices.EQUITIES,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def apply(self, account, action, amount):
        """What create() now does for the OBE leg."""
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()

    def test_an_asset_opening_balance_raises_equity(self):
        obe = self.obe()

        self.apply(obe, "addition", Decimal("250"))

        self.assertEqual(
            Decimal(str(obe.opening_balance)), self.BASELINE + Decimal("250")
        )

    def test_a_liability_opening_balance_lowers_equity(self):
        obe = self.obe()

        self.apply(obe, "substraction", Decimal("250"))

        self.assertEqual(
            Decimal(str(obe.opening_balance)), self.BASELINE - Decimal("250")
        )

    def test_the_two_directions_cancel(self):
        obe = self.obe()

        self.apply(obe, "addition", Decimal("250"))
        self.apply(obe, "substraction", Decimal("250"))

        self.assertEqual(Decimal(str(obe.opening_balance)), self.BASELINE)

    def test_the_balance_is_readable_immediately_after_the_move(self):
        """The connector records it as `last_balance` on the very next line.

        `update_opening_balance` uses an `F()` expression, which leaves the
        in-memory instance holding the OLD figure unless it refreshes. Without
        the refresh the ledger would carry the pre-update balance.
        """
        obe = self.obe()

        update_opening_balance(
            obe, balance_operation_for_action("addition"), Decimal("250"), 0
        )

        self.assertEqual(
            Decimal(str(obe.opening_balance)),
            self.BASELINE + Decimal("250"),
            "the helper must refresh, or the connector stamps a stale balance",
        )

    def test_concurrent_creations_do_not_lose_an_increment(self):
        """The lost update. `+=` then save writes back a figure read before.

        Simulated by holding a second in-memory copy, which is exactly what two
        requests have.
        """
        obe = self.obe()
        stale_copy = ChartOfAccount.objects.get(pk=obe.pk)

        update_opening_balance(
            obe, balance_operation_for_action("addition"), Decimal("100"), 0
        )
        update_opening_balance(
            stale_copy, balance_operation_for_action("addition"), Decimal("200"), 0
        )

        obe.refresh_from_db()
        self.assertEqual(
            Decimal(str(obe.opening_balance)),
            self.BASELINE + Decimal("300"),
            "both increments must land; a read-modify-write loses one",
        )

    def test_the_old_read_modify_write_loses_one(self):
        """Kept as the executable statement of the defect."""
        obe = self.obe()
        stale_copy = ChartOfAccount.objects.get(pk=obe.pk)

        # What the code did, twice, from two requests.
        obe.opening_balance += Decimal("100")
        obe.save()
        stale_copy.opening_balance += Decimal("200")
        stale_copy.save()

        obe.refresh_from_db()
        self.assertEqual(
            Decimal(str(obe.opening_balance)),
            self.BASELINE + Decimal("200"),
            "the 100 is gone -- this is the lost update",
        )


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.serializers import chart_of_accounts

        return inspect.getsource(chart_of_accounts)

    def test_a_missing_obe_account_is_a_validation_error(self):
        source = self.source()

        self.assertIn(
            "if opening_balance != 0 and opening_balance_equity_charter_account is None:",
            source,
        )
        self.assertIn("has no 'Opening Balance Equity' account", source)

    def test_the_guard_only_fires_when_an_opening_balance_is_given(self):
        """An account with no opening balance must still create in a company
        that lacks OBE -- the guard must not become a new way to fail."""
        source = self.source()

        self.assertIn("opening_balance != 0 and", source)

    def test_the_obe_write_goes_through_the_helper(self):
        source = self.source()

        self.assertIn("update_opening_balance(\n                opening_balance_equity_charter_account,", source)
        self.assertIn("balance_operation_for_action(obe_action)", source)

    def test_no_raw_read_modify_write_remains(self):
        source = self.source()

        self.assertNotIn("opening_balance_equity_charter_account.opening_balance += ", source)
        self.assertNotIn("opening_balance_equity_charter_account.opening_balance -= ", source)
        self.assertNotIn("opening_balance_equity_charter_account.save_dirty_fields()", source)

    def test_the_two_branches_collapsed_to_one_derived_action(self):
        """They differed only in the direction, which is now derived."""
        source = self.source()

        self.assertIn('obe_action = (\n                "addition"', source)
        self.assertIn('else "substraction"', source)
