"""A stock adjustment must move the stored balance the way its journal does.

All four legs of `PrivateWeStockAdjustmentSerializer.create` had the right
accounting side and the wrong stored balance:

    ADDITION   inventory   journal DEBIT   balance subtracted
               adjustment  journal CREDIT  balance added
    DEDUCTION  adjustment  journal DEBIT   balance subtracted
               inventory   journal CREDIT  balance added

`update_opening_balance` reads its CREDIT/DEBIT argument as add/subtract, not as
an accounting side, and all four calls passed a side. So writing stock UP
reduced the recorded value of inventory while the journal increased it, and
writing it DOWN did the reverse -- on every adjustment, in both directions.

The entries balanced throughout, which is why nothing noticed: this is the shape
the write-time balance check cannot see.

Also here: `StockAdjustmentItemKindChoices.INCREASE` does not exist. Adding a
line to an existing adjustment raised AttributeError before the create ran,
because a `.get` default is evaluated eagerly. That endpoint has never worked.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    get_debit_or_credit,
    update_opening_balance,
)

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices

from stockio.choices import StockAdjustmentItemKindChoices


class AdjustmentLegTests(TestCase):
    BASELINE = Decimal("1000")
    VALUE = Decimal("250")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def setUp(self):
        super().setUp()
        self.inventory = self.account(
            "Inventory Asset", ChartOfAccountKindChoices.ASSETS
        )
        self.adjustment = self.account(
            "Inventory Shrinkage", ChartOfAccountKindChoices.EXPENSES
        )

    def post(self, account, side):
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), self.VALUE, 0
        )
        account.refresh_from_db()
        return action, get_debit_or_credit(account.kind)[action]

    def test_writing_stock_up_increases_recorded_inventory(self):
        """The defect: the journal debited and the balance subtracted."""
        action, side = self.post(
            self.inventory, JournalEntryConnectorKindChoices.DEBIT
        )

        self.assertEqual(side, JournalEntryConnectorKindChoices.DEBIT)
        self.assertEqual(
            Decimal(str(self.inventory.opening_balance)),
            self.BASELINE + self.VALUE,
        )

    def test_writing_stock_up_reduces_the_adjustment_account(self):
        action, side = self.post(
            self.adjustment, JournalEntryConnectorKindChoices.CREDIT
        )

        self.assertEqual(side, JournalEntryConnectorKindChoices.CREDIT)
        self.assertEqual(
            Decimal(str(self.adjustment.opening_balance)),
            self.BASELINE - self.VALUE,
        )

    def test_writing_stock_down_reduces_recorded_inventory(self):
        action, side = self.post(
            self.inventory, JournalEntryConnectorKindChoices.CREDIT
        )

        self.assertEqual(side, JournalEntryConnectorKindChoices.CREDIT)
        self.assertEqual(
            Decimal(str(self.inventory.opening_balance)),
            self.BASELINE - self.VALUE,
        )

    def test_writing_stock_down_recognises_the_cost(self):
        action, side = self.post(
            self.adjustment, JournalEntryConnectorKindChoices.DEBIT
        )

        self.assertEqual(side, JournalEntryConnectorKindChoices.DEBIT)
        self.assertEqual(
            Decimal(str(self.adjustment.opening_balance)),
            self.BASELINE + self.VALUE,
        )

    def test_up_then_down_nets_to_zero(self):
        """The pair has to be a mirror, or repeated adjustments drift."""
        self.post(self.inventory, JournalEntryConnectorKindChoices.DEBIT)
        self.post(self.inventory, JournalEntryConnectorKindChoices.CREDIT)

        self.assertEqual(
            Decimal(str(self.inventory.opening_balance)), self.BASELINE
        )

    def test_every_account_kind_lands_on_the_asked_side(self):
        for kind in ChartOfAccountKindChoices.values:
            for side in (
                JournalEntryConnectorKindChoices.DEBIT,
                JournalEntryConnectorKindChoices.CREDIT,
            ):
                with self.subTest(kind=kind, side=side):
                    account = self.account(f"A {kind} {side}", kind)
                    _action, landed = self.post(account, side)
                    self.assertEqual(landed, side)


class AdjustmentKindChoiceTests(TestCase):
    def test_increase_is_not_a_member(self):
        """What made adding a line to an adjustment a 500."""
        self.assertFalse(hasattr(StockAdjustmentItemKindChoices, "INCREASE"))

    def test_addition_is(self):
        self.assertTrue(hasattr(StockAdjustmentItemKindChoices, "ADDITION"))

    def test_the_serializer_no_longer_references_increase(self):
        import inspect

        from weapi.django_rest.serializers import stock

        self.assertNotIn(
            "StockAdjustmentItemKindChoices.INCREASE", inspect.getsource(stock)
        )
