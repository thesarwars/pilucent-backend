"""Paying sales tax must reduce the liability and the bank, not raise both.

`PrivateWeSalesTaxListSerializer.create` posted both legs like this:

    update_opening_balance(sales_tax_account, "credit", total_tax, 0)
    connector_data.append((sales_tax_account, "substraction", ...))

    update_opening_balance(charter_account, "credit", total_tax, 0)
    connector_data.append((charter_account, "substraction", ...))

The SIDES were right by luck. `"substraction"` is a DEBIT on a liability and a
CREDIT on an asset, which is exactly what paying a tax bill needs -- debit the
debt, credit the bank -- so the journal entry balanced and looked correct.

The BALANCES were both backwards. `"credit"` means add, while `"substraction"`
pairs with subtract. So recording a tax payment pushed the liability UP and the
bank UP: the debt grew by what was paid off, and the money that left the account
appeared to arrive in it.

That is the shape the write-time balance check cannot see. The entry balances;
it is the stored balances beside it that are wrong.
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


class SalesTaxPaymentTests(TestCase):
    BASELINE = Decimal("1000")
    TAX = Decimal("250.00")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Pilucent INC")

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def pay(self, account, side):
        """The posting the serializer now does for one leg."""
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), self.TAX, 0
        )
        account.refresh_from_db()
        return action

    def test_the_liability_goes_down(self):
        payable = self.account(
            "Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES
        )

        action = self.pay(payable, JournalEntryConnectorKindChoices.DEBIT)

        self.assertEqual(
            get_debit_or_credit(payable.kind)[action],
            JournalEntryConnectorKindChoices.DEBIT,
        )
        self.assertEqual(
            Decimal(str(payable.opening_balance)), self.BASELINE - self.TAX
        )

    def test_the_bank_goes_down(self):
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)

        action = self.pay(bank, JournalEntryConnectorKindChoices.CREDIT)

        self.assertEqual(
            get_debit_or_credit(bank.kind)[action],
            JournalEntryConnectorKindChoices.CREDIT,
        )
        self.assertEqual(
            Decimal(str(bank.opening_balance)), self.BASELINE - self.TAX
        )

    def test_the_old_pairing_moved_both_the_wrong_way(self):
        """What the code did before, stated so the regression is visible."""
        payable = self.account(
            "Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES
        )
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)

        # The old call: "credit" is add, on both legs.
        update_opening_balance(payable, "credit", self.TAX, 0)
        update_opening_balance(bank, "credit", self.TAX, 0)

        payable.refresh_from_db()
        bank.refresh_from_db()
        self.assertEqual(
            Decimal(str(payable.opening_balance)), self.BASELINE + self.TAX,
            "the debt grew by what was paid off",
        )
        self.assertEqual(
            Decimal(str(bank.opening_balance)), self.BASELINE + self.TAX,
            "money that left the account appeared to arrive in it",
        )

    def test_both_legs_still_balance_the_entry(self):
        """The sides were already right; the entry balanced before and after."""
        payable = self.account(
            "Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES
        )
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)

        tax_side = get_debit_or_credit(payable.kind)[
            action_for_side(payable.kind, JournalEntryConnectorKindChoices.DEBIT)
        ]
        bank_side = get_debit_or_credit(bank.kind)[
            action_for_side(bank.kind, JournalEntryConnectorKindChoices.CREDIT)
        ]

        self.assertEqual(tax_side, JournalEntryConnectorKindChoices.DEBIT)
        self.assertEqual(bank_side, JournalEntryConnectorKindChoices.CREDIT)

    def test_an_oddly_typed_account_still_lands_on_the_right_side(self):
        """The sides were right only for a liability and an asset.

        A company paying from a credit card -- a LIABILITY -- got a DEBIT from
        the hard-coded `"substraction"`, which is the wrong side entirely.
        """
        card = self.account("Company Visa", ChartOfAccountKindChoices.LIABILITIES)

        action = self.pay(card, JournalEntryConnectorKindChoices.CREDIT)

        self.assertEqual(
            get_debit_or_credit(card.kind)[action],
            JournalEntryConnectorKindChoices.CREDIT,
        )
        self.assertNotEqual(action, "substraction")
