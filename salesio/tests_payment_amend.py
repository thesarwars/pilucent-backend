"""Amending a payment receipt must move the ledger the way the posting did.

Both legs of `PrivateWeSalePaymentReceiveDetailsSerializer.update` went through
`update_opening_balance(account, "update", new, old)`, which picks its direction
from whether the figure rose or fell rather than from what the leg is.

Receiving a payment CREDITS the receivable -- the customer owes less. So raising
a receipt from 100 to 150 should credit a further 50. The "update" op added 50 to
the stored balance and recorded "addition", which `get_debit_or_credit` resolves
to a DEBIT on an asset: the amendment moved the balance and the journal both the
opposite way from the posting it was amending.

The deposit leg was right, but only while the deposit account was an asset. It
reads no account kind, so it stopped mirroring the posting the moment the posting
became kind-aware -- a credit card deposit account amends one way and posts the
other.

Also here: the receivable branch read `.opening_balance` off the dict
`update_opening_balance` returns, so it raised AttributeError before writing
anything. Any amendment that changed a receipt's total was a 500.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    amend_leg,
    get_debit_or_credit,
    update_opening_balance,
    balance_operation_for_action,
)

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices


class AmendLegTests(TestCase):
    BASELINE = Decimal("1000")

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

    def post(self, account, side, amount):
        """What the create path does."""
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()
        return action

    def test_an_unchanged_figure_writes_no_leg(self):
        account = self.account("A/R", ChartOfAccountKindChoices.ASSETS)

        self.assertIsNone(
            amend_leg(
                account,
                JournalEntryConnectorKindChoices.CREDIT,
                Decimal("100"),
                Decimal("100"),
            )
        )
        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)

    def test_raising_a_receipt_credits_the_receivable_further(self):
        """The defect: it debited."""
        receivable = self.account("A/R", ChartOfAccountKindChoices.ASSETS)

        action, amount = amend_leg(
            receivable,
            JournalEntryConnectorKindChoices.CREDIT,
            Decimal("150"),
            Decimal("100"),
        )

        self.assertEqual(amount, Decimal("50"))
        self.assertEqual(
            self.side_of(receivable, action),
            JournalEntryConnectorKindChoices.CREDIT,
        )
        receivable.refresh_from_db()
        self.assertEqual(
            Decimal(str(receivable.opening_balance)), self.BASELINE - Decimal("50")
        )

    def test_lowering_a_receipt_debits_the_receivable_back(self):
        receivable = self.account("A/R", ChartOfAccountKindChoices.ASSETS)

        action, amount = amend_leg(
            receivable,
            JournalEntryConnectorKindChoices.CREDIT,
            Decimal("60"),
            Decimal("100"),
        )

        self.assertEqual(amount, Decimal("40"))
        self.assertEqual(
            self.side_of(receivable, action),
            JournalEntryConnectorKindChoices.DEBIT,
        )
        receivable.refresh_from_db()
        self.assertEqual(
            Decimal(str(receivable.opening_balance)), self.BASELINE + Decimal("40")
        )

    def test_amending_up_then_back_down_nets_to_zero(self):
        """For every kind, on both legs -- or repeated edits drift."""
        for kind in ChartOfAccountKindChoices.values:
            for side in (
                JournalEntryConnectorKindChoices.CREDIT,
                JournalEntryConnectorKindChoices.DEBIT,
            ):
                with self.subTest(kind=kind, side=side):
                    account = self.account(f"A {kind} {side}", kind)

                    amend_leg(account, side, Decimal("150"), Decimal("100"))
                    amend_leg(account, side, Decimal("100"), Decimal("150"))

                    account.refresh_from_db()
                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )

    def test_an_amendment_continues_the_posting_for_every_kind(self):
        """Post 100, then amend to 150: the same as having posted 150.

        This is the mirror property. It is what the hard-coded add/subtract
        could not hold once the posting leg started reading the account kind.
        """
        for kind in ChartOfAccountKindChoices.values:
            for side in (
                JournalEntryConnectorKindChoices.CREDIT,
                JournalEntryConnectorKindChoices.DEBIT,
            ):
                with self.subTest(kind=kind, side=side):
                    stepped = self.account(f"Stepped {kind} {side}", kind)
                    self.post(stepped, side, Decimal("100"))
                    amend_leg(stepped, side, Decimal("150"), Decimal("100"))
                    stepped.refresh_from_db()

                    direct = self.account(f"Direct {kind} {side}", kind)
                    self.post(direct, side, Decimal("150"))

                    self.assertEqual(
                        Decimal(str(stepped.opening_balance)),
                        Decimal(str(direct.opening_balance)),
                    )

    def test_the_deposit_leg_holds_on_a_credit_card(self):
        """The kind the old code got wrong: a liability deposit account."""
        card = self.account("Company Visa", ChartOfAccountKindChoices.LIABILITIES)

        self.post(card, JournalEntryConnectorKindChoices.DEBIT, Decimal("100"))
        after_post = Decimal(str(card.opening_balance))

        action, _amount = amend_leg(
            card,
            JournalEntryConnectorKindChoices.DEBIT,
            Decimal("150"),
            Decimal("100"),
        )

        self.assertEqual(
            self.side_of(card, action), JournalEntryConnectorKindChoices.DEBIT
        )
        card.refresh_from_db()
        self.assertEqual(
            Decimal(str(card.opening_balance)),
            after_post - Decimal("50"),
            "the posting subtracted on this kind, so the amendment must too",
        )


class TheOldUpdateOpTests(AmendLegTests):
    """What `"update"` actually did, kept as the statement of the defect.

    Nothing calls it this way any more, so without this the reason the call
    sites changed stops being written down anywhere executable.
    """

    def test_the_update_op_moved_the_receivable_the_wrong_way(self):
        receivable = self.account("A/R", ChartOfAccountKindChoices.ASSETS)

        returned = update_opening_balance(
            receivable, "update", Decimal("150"), Decimal("100")
        )
        receivable.refresh_from_db()

        # Raising the receipt by 50 raised the receivable by 50; receiving more
        # money must lower what the customer owes.
        self.assertEqual(
            Decimal(str(receivable.opening_balance)), self.BASELINE + Decimal("50")
        )
        # And the action it recorded resolves to the opposite side too.
        self.assertEqual(
            self.side_of(receivable, returned["action_type"]),
            JournalEntryConnectorKindChoices.DEBIT,
        )
        self.assertEqual(
            self.side_of(
                receivable,
                amend_leg(
                    self.account("A/R b", ChartOfAccountKindChoices.ASSETS),
                    JournalEntryConnectorKindChoices.CREDIT,
                    Decimal("150"),
                    Decimal("100"),
                )[0],
            ),
            JournalEntryConnectorKindChoices.CREDIT,
        )

    def test_the_update_op_returns_a_dict_with_no_opening_balance(self):
        """Why the receivable branch was a 500 rather than merely wrong."""
        returned = update_opening_balance(
            self.account("A/R", ChartOfAccountKindChoices.ASSETS),
            "update",
            Decimal("150"),
            Decimal("100"),
        )

        self.assertIsInstance(returned, dict)
        with self.assertRaises(AttributeError):
            returned.opening_balance

    def test_the_update_op_ignores_the_account_kind(self):
        """So it could not mirror a posting leg that reads it."""
        results = {}
        for kind in ChartOfAccountKindChoices.values:
            account = self.account(f"A {kind}", kind)
            update_opening_balance(account, "update", Decimal("150"), Decimal("100"))
            account.refresh_from_db()
            results[kind] = Decimal(str(account.opening_balance))

        self.assertEqual(
            set(results.values()),
            {self.BASELINE + Decimal("50")},
            "every kind moved the same way, which is the bug",
        )


class CallSiteTests(TestCase):
    """Assert the serializer routes through the helper, not just that it exists."""

    def source(self):
        import inspect

        from weapi.django_rest.serializers import sales

        return inspect.getsource(sales)

    def test_the_payment_amend_no_longer_uses_the_update_op(self):
        source = self.source()

        self.assertNotIn('"update",\n            validated_data["total"]', source)
        self.assertNotIn('"update",\n            validated_data["deposit"]', source)

    def test_both_amend_legs_call_amend_leg(self):
        source = self.source()

        self.assertIn("receivable_amend = amend_leg(", source)
        self.assertIn("deposit_amend = amend_leg(", source)

    def test_both_amend_legs_track_total(self):
        """The posting put `total` on both legs, so the amendment must too.

        The deposit leg amended on the change in `deposit`. An edit moving the
        two payload fields by different amounts then moved the receivable leg by
        one figure and its only counterpart by another, leaving the entry
        unbalanced -- which the write-time guard reports but cannot prevent.
        """
        source = self.source()
        deposit_call = source.split("deposit_amend = amend_leg(")[1].split(")")[0]

        self.assertIn('validated_data["total"]', deposit_call)
        self.assertNotIn('validated_data["deposit"]', deposit_call)
        self.assertNotIn("instance.deposit", deposit_call)

    def test_the_dict_attribute_read_is_gone(self):
        """It raised AttributeError, so this path had never run to completion."""
        self.assertNotIn(
            "payment_receive_debit_or_credit.opening_balance", self.source()
        )
