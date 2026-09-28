from django.test import SimpleTestCase

from accounts.choices import ChartOfAccountKindChoices
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    get_debit_or_credit,
    get_migration_undo_balance_operation,
)
from journalio.choices import JournalEntryConnectorKindChoices


class GetMigrationUndoBalanceOperationTests(SimpleTestCase):
    """Undo op must match migration import's update_opening_balance convention."""

    def test_asset_addition_deposit_uses_debit_to_subtract(self):
        """Checking account: import CREDIT-add, connector DEBIT — undo must DEBIT."""
        undo = get_migration_undo_balance_operation(
            type("Account", (), {"kind": ChartOfAccountKindChoices.ASSETS})(),
            JournalEntryConnectorKindChoices.DEBIT,
        )
        self.assertEqual(undo, JournalEntryConnectorKindChoices.DEBIT)

    def test_asset_substraction_inventory_uses_credit_to_add_back(self):
        undo = get_migration_undo_balance_operation(
            type("Account", (), {"kind": ChartOfAccountKindChoices.ASSETS})(),
            JournalEntryConnectorKindChoices.CREDIT,
        )
        self.assertEqual(undo, JournalEntryConnectorKindChoices.CREDIT)

    def test_income_addition_uses_debit_to_subtract(self):
        undo = get_migration_undo_balance_operation(
            type("Account", (), {"kind": ChartOfAccountKindChoices.INCOMES})(),
            JournalEntryConnectorKindChoices.CREDIT,
        )
        self.assertEqual(undo, JournalEntryConnectorKindChoices.DEBIT)

    def test_expense_addition_cogs_uses_debit_to_subtract(self):
        undo = get_migration_undo_balance_operation(
            type("Account", (), {"kind": ChartOfAccountKindChoices.EXPENSES})(),
            JournalEntryConnectorKindChoices.DEBIT,
        )
        self.assertEqual(undo, JournalEntryConnectorKindChoices.DEBIT)

    def test_liability_addition_tax_uses_debit_to_subtract(self):
        undo = get_migration_undo_balance_operation(
            type("Account", (), {"kind": ChartOfAccountKindChoices.LIABILITIES})(),
            JournalEntryConnectorKindChoices.CREDIT,
        )
        self.assertEqual(undo, JournalEntryConnectorKindChoices.DEBIT)


class ActionForSideTests(SimpleTestCase):
    """A leg whose direction the transaction fixes, not the account.

    Cash back on a deposit is always a debit, whatever account it is taken to.
    Hard-coding "addition" only lands on DEBIT for assets and expenses, so
    taking cash back to a liability posted it as a credit and unbalanced the
    entry by twice the amount -- production had that firing daily.
    """

    def test_a_debit_leg_resolves_per_account_kind(self):
        self.assertEqual(
            action_for_side(
                ChartOfAccountKindChoices.ASSETS,
                JournalEntryConnectorKindChoices.DEBIT,
            ),
            "addition",
        )
        self.assertEqual(
            action_for_side(
                ChartOfAccountKindChoices.LIABILITIES,
                JournalEntryConnectorKindChoices.DEBIT,
            ),
            "substraction",
        )
        self.assertEqual(
            action_for_side(
                ChartOfAccountKindChoices.EQUITIES,
                JournalEntryConnectorKindChoices.DEBIT,
            ),
            "substraction",
        )

    def test_the_resolved_action_really_posts_that_side(self):
        for kind in (
            ChartOfAccountKindChoices.ASSETS,
            ChartOfAccountKindChoices.LIABILITIES,
            ChartOfAccountKindChoices.EQUITIES,
            ChartOfAccountKindChoices.INCOMES,
            ChartOfAccountKindChoices.EXPENSES,
        ):
            for side in (
                JournalEntryConnectorKindChoices.DEBIT,
                JournalEntryConnectorKindChoices.CREDIT,
            ):
                action = action_for_side(kind, side)
                self.assertEqual(
                    get_debit_or_credit(kind)[action], side, f"{kind}/{side}"
                )

    def test_an_unknown_kind_falls_back_rather_than_raising(self):
        self.assertEqual(
            action_for_side("NOT_A_KIND", JournalEntryConnectorKindChoices.DEBIT),
            "addition",
        )

    def test_the_balance_update_matches_the_connector_action(self):
        """`update_opening_balance` takes add/subtract, not an accounting side."""
        self.assertEqual(
            balance_operation_for_action("addition"),
            JournalEntryConnectorKindChoices.CREDIT,
        )
        self.assertEqual(
            balance_operation_for_action("substraction"),
            JournalEntryConnectorKindChoices.DEBIT,
        )


class DepositCashBackTests(SimpleTestCase):
    """The production case: a 399 deposit taking 100 cash back to a liability."""

    def _sides(self, cash_back_kind, cash_back_action):
        total, cash_back = 399, 100
        legs = [
            (ChartOfAccountKindChoices.EXPENSES, "substraction", total),
            (ChartOfAccountKindChoices.ASSETS, "addition", total - cash_back),
            (cash_back_kind, cash_back_action, cash_back),
        ]
        debits = credits = 0
        for kind, action, amount in legs:
            if (
                get_debit_or_credit(kind)[action]
                == JournalEntryConnectorKindChoices.DEBIT
            ):
                debits += amount
            else:
                credits += amount
        return debits, credits

    def test_it_balances_whatever_kind_the_cash_back_account_is(self):
        for kind in (
            ChartOfAccountKindChoices.ASSETS,
            ChartOfAccountKindChoices.LIABILITIES,
            ChartOfAccountKindChoices.EQUITIES,
            ChartOfAccountKindChoices.EXPENSES,
        ):
            action = action_for_side(kind, JournalEntryConnectorKindChoices.DEBIT)
            debits, credits = self._sides(kind, action)
            self.assertEqual(debits, credits, kind)

    def test_the_old_hardcoded_action_reproduces_the_production_gap(self):
        debits, credits = self._sides(
            ChartOfAccountKindChoices.LIABILITIES, "addition"
        )
        self.assertEqual(debits - credits, -200)
