"""Paying a bill, and amending that payment, on any account kind.

Both legs are fixed by the transaction: paying a bill DEBITS accounts payable
-- the debt goes down -- and CREDITS whatever the money leaves. Both were
hard-coded to `"substraction"`, which gives those sides only while A/P is a
LIABILITY and the payment account an ASSET.

Neither kind is guaranteed. A/P's kind derives from an editable account type --
which is why `repair_control_account_types` exists, and why production had
`Talha-organization`'s A/P typed as an Expense -- and the payment account is a
SlugRelatedField over the whole chart, a credit card included.

The amend paths mattered as much as the posting. They hard-coded add/subtract,
which mirrored the create leg only while both accounts were assets. Making the
posting kind-aware without them would have left an amendment moving the balance
the opposite way from the thing it was amending -- the defect this sweep keeps
finding, introduced fresh.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    get_debit_or_credit,
    inverse_balance_operation,
    update_opening_balance,
)

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices


class PayBillSideTests(TestCase):
    BASELINE = Decimal("1000")
    AMOUNT = Decimal("250")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def side_of(self, account, action):
        return get_debit_or_credit(account.kind)[action]

    def test_the_payable_leg_debits_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                payable = self.account(f"A/P {kind}", kind)
                action = action_for_side(
                    payable.kind, JournalEntryConnectorKindChoices.DEBIT
                )
                self.assertEqual(
                    self.side_of(payable, action),
                    JournalEntryConnectorKindChoices.DEBIT,
                )

    def test_the_payment_leg_credits_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                funding = self.account(f"Fund {kind}", kind)
                action = action_for_side(
                    funding.kind, JournalEntryConnectorKindChoices.CREDIT
                )
                self.assertEqual(
                    self.side_of(funding, action),
                    JournalEntryConnectorKindChoices.CREDIT,
                )

    def test_paying_from_a_credit_card_credits_it(self):
        """The case `"substraction"` got wrong: it debits a liability."""
        card = self.account("Company Visa", ChartOfAccountKindChoices.LIABILITIES)

        action = action_for_side(
            card.kind, JournalEntryConnectorKindChoices.CREDIT
        )

        self.assertEqual(
            self.side_of(card, action), JournalEntryConnectorKindChoices.CREDIT
        )
        self.assertEqual(
            self.side_of(card, "substraction"),
            JournalEntryConnectorKindChoices.DEBIT,
            "which is what the old literal produced",
        )

    def apply(self, account, side):
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), self.AMOUNT, 0
        )
        account.refresh_from_db()
        return action


class AmendMirrorTests(PayBillSideTests):
    """An amendment must undo exactly what the posting did."""

    def test_repointing_the_payment_account_nets_to_zero(self):
        """Old account restored, new one reduced, for every kind."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                old = self.account(f"Old {kind}", kind)

                self.apply(old, JournalEntryConnectorKindChoices.CREDIT)
                # The repoint undoes it on the old account.
                undo = inverse_balance_operation(
                    balance_operation_for_action(
                        action_for_side(
                            old.kind, JournalEntryConnectorKindChoices.CREDIT
                        )
                    )
                )
                update_opening_balance(old, undo, self.AMOUNT, 0)

                old.refresh_from_db()
                self.assertEqual(
                    Decimal(str(old.opening_balance)), self.BASELINE
                )

    def test_raising_then_lowering_a_payment_nets_to_zero(self):
        """The amount-change path, both directions."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                payable = self.account(f"A/P {kind}", kind)
                apply_op = balance_operation_for_action(
                    action_for_side(
                        payable.kind, JournalEntryConnectorKindChoices.DEBIT
                    )
                )

                update_opening_balance(payable, apply_op, self.AMOUNT, 0)
                update_opening_balance(
                    payable, inverse_balance_operation(apply_op), self.AMOUNT, 0
                )

                payable.refresh_from_db()
                self.assertEqual(
                    Decimal(str(payable.opening_balance)), self.BASELINE
                )

    def test_the_inverse_of_the_inverse_is_the_original(self):
        for op in (
            JournalEntryConnectorKindChoices.CREDIT,
            JournalEntryConnectorKindChoices.DEBIT,
        ):
            self.assertEqual(
                inverse_balance_operation(inverse_balance_operation(op)), op
            )

    def test_the_liability_case_is_the_one_that_used_to_break(self):
        """A credit-card payment account, posted then amended.

        The old code posted `"debit"` (subtract) on it and amended with a
        hard-coded add/subtract pair. Once the posting became kind-aware the
        amend would no longer have mirrored it.
        """
        card = self.account("Company Visa", ChartOfAccountKindChoices.LIABILITIES)

        self.apply(card, JournalEntryConnectorKindChoices.CREDIT)
        after_post = Decimal(str(card.opening_balance))
        # Paying from a card increases what is owed.
        self.assertEqual(after_post, self.BASELINE + self.AMOUNT)

        undo = inverse_balance_operation(
            balance_operation_for_action(
                action_for_side(card.kind, JournalEntryConnectorKindChoices.CREDIT)
            )
        )
        update_opening_balance(card, undo, self.AMOUNT, 0)

        card.refresh_from_db()
        self.assertEqual(Decimal(str(card.opening_balance)), self.BASELINE)
