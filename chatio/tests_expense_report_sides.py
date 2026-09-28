"""An expense report posts a bill and its payment; all four legs were literals.

`_create_purchase_from_report` and `_create_payment_from_report` hard-coded
"addition" on the bill and "substraction" on the payment. Both give the intended
sides only while payables is a LIABILITY, the expense account an EXPENSE and the
payment account an ASSET.

None of those three is guaranteed. A/P's kind derives from an editable account
type -- which is what `repair_control_account_types` exists to correct, and why
production had a company's A/P typed as an Expense -- the expense account is
whatever the employee picked on the report, and the payment account can be a
credit card, on which "substraction" resolves to a DEBIT: an expense paid by
card reduced the card balance instead of increasing it.

Because both legs of each entry carried the same literal, the entry still
balanced whenever the two accounts' kinds happened to agree, which is the shape
the write-time balance check cannot see.
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


class ExpenseReportLegTests(TestCase):
    BASELINE = Decimal("1000")
    AMOUNT = Decimal("250")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    _seq = 0

    def account(self, title, kind):
        # Unique per call. `unique_title_per_company_ci` forbids two live accounts
        # with one title in a company, and these loops reuse a kind. The tests
        # assert on sides and balances, never on the title.
        type(self)._seq += 1
        return ChartOfAccount.objects.create(
            company=self.company, title=f"{title} #{type(self)._seq}", kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def side_of(self, account, action):
        return get_debit_or_credit(account.kind)[action]

    def post(self, account, side):
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), self.AMOUNT, 0
        )
        account.refresh_from_db()
        return action

    def test_the_bill_credits_payables_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                payable = self.account(f"A/P {kind}", kind)
                self.assertEqual(
                    self.side_of(
                        payable,
                        action_for_side(
                            payable.kind, JournalEntryConnectorKindChoices.CREDIT
                        ),
                    ),
                    JournalEntryConnectorKindChoices.CREDIT,
                )

    def test_the_bill_debits_the_expense_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                expense = self.account(f"Expense {kind}", kind)
                self.assertEqual(
                    self.side_of(
                        expense,
                        action_for_side(
                            expense.kind, JournalEntryConnectorKindChoices.DEBIT
                        ),
                    ),
                    JournalEntryConnectorKindChoices.DEBIT,
                )

    def test_paying_by_credit_card_credits_the_card(self):
        """The case "substraction" got backwards."""
        card = self.account("Company Visa", ChartOfAccountKindChoices.LIABILITIES)

        action = self.post(card, JournalEntryConnectorKindChoices.CREDIT)

        self.assertEqual(
            self.side_of(card, action), JournalEntryConnectorKindChoices.CREDIT
        )
        self.assertEqual(
            self.side_of(card, "substraction"),
            JournalEntryConnectorKindChoices.DEBIT,
            "which is what the old literal produced",
        )
        self.assertEqual(
            Decimal(str(card.opening_balance)),
            self.BASELINE + self.AMOUNT,
            "paying by card increases what is owed on it",
        )

    def test_payables_typed_as_an_expense_still_credits_on_the_bill(self):
        """Production had exactly this: A/P carrying an Expense account type."""
        payable = self.account("A/P", ChartOfAccountKindChoices.EXPENSES)

        action = self.post(payable, JournalEntryConnectorKindChoices.CREDIT)

        self.assertEqual(
            self.side_of(payable, action), JournalEntryConnectorKindChoices.CREDIT
        )
        self.assertEqual(
            self.side_of(payable, "addition"),
            JournalEntryConnectorKindChoices.DEBIT,
            "which is what the old literal produced",
        )

    def test_the_bill_and_its_payment_net_to_zero_on_payables(self):
        """Bill then pay: payables ends where it started, for every kind."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                payable = self.account(f"A/P {kind}", kind)

                self.post(payable, JournalEntryConnectorKindChoices.CREDIT)
                self.post(payable, JournalEntryConnectorKindChoices.DEBIT)

                self.assertEqual(
                    Decimal(str(payable.opening_balance)), self.BASELINE
                )

    def test_each_entry_has_one_debit_and_one_credit(self):
        """Both legs carried the same literal, so both could land the same side."""
        for payable_kind in ChartOfAccountKindChoices.values:
            for other_kind in ChartOfAccountKindChoices.values:
                with self.subTest(payable=payable_kind, other=other_kind):
                    payable = self.account(f"A/P {payable_kind}", payable_kind)
                    expense = self.account(f"Exp {other_kind}", other_kind)

                    sides = {
                        self.side_of(
                            payable,
                            action_for_side(
                                payable.kind,
                                JournalEntryConnectorKindChoices.CREDIT,
                            ),
                        ),
                        self.side_of(
                            expense,
                            action_for_side(
                                expense.kind,
                                JournalEntryConnectorKindChoices.DEBIT,
                            ),
                        ),
                    }
                    self.assertEqual(
                        sides,
                        {
                            JournalEntryConnectorKindChoices.DEBIT,
                            JournalEntryConnectorKindChoices.CREDIT,
                        },
                    )


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from chatio.django_rest.helpers import expense_report

        return inspect.getsource(expense_report)

    def test_no_leg_carries_a_hard_coded_action(self):
        source = self.source()

        for literal in ('"addition",', '"substraction",'):
            self.assertNotIn(literal, source)

    def test_all_four_legs_resolve_from_the_side(self):
        source = self.source()

        self.assertEqual(source.count("action_for_side("), 4)
        self.assertEqual(source.count("balance_operation_for_action("), 4)
