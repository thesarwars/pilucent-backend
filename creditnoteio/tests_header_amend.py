"""Amending a credit note's header moved four balances the wrong way.

`PrivateWeCreditNoteDetailsSerializer.update` amended A/R, A/P and the
customer/supplier balances through
`update_opening_balance(obj, "update", new, old)`. That op reads its direction
from whether the figure ROSE, not from what the posting did.

All four SUBTRACT on posting -- a sale credit note lowers what the customer owes
and credits A/R; a vendor credit lowers what we owe and debits A/P. So raising a
note from 100 to 150 moved each of them +50 where they had to move -50: an error
of twice the delta, on the most frequent edit in the module.

Two of the four have no account kind. `Customer` and `Supplier` carry an
`opening_balance` and are passed to `update_opening_balance` like accounts are,
but there is no side to resolve, so they take `amend_balance` -- the posting's
own operation, continued -- rather than `amend_leg`.

Also here: the SALE branch's tax amend was REMOVED, not corrected. It moved the
balance of "Sales Tax Payable", and the SALE branch of `create` never posts to
that account -- it posts to `tax_group.sales_tax_account` per item and to the
auto-tax breakdown accounts. The `.filter(account=payable_account).first()`
beneath it therefore always returned None, which is why nothing looked wrong.
Flipping its sign would only have corrupted that account in the other direction.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    amend_balance,
    amend_leg,
    balance_operation_for_action,
    update_opening_balance,
)

from companyio.models import Company
from customerio.models import Customer

from journalio.choices import JournalEntryConnectorKindChoices


DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT


class HeaderAmendTests(TestCase):
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

    def post(self, account, side, amount):
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()

    def test_raising_a_sale_credit_note_lowers_the_receivable_further(self):
        receivable = self.account("A/R", ChartOfAccountKindChoices.ASSETS)

        self.post(receivable, CREDIT, Decimal("100"))
        amend_leg(receivable, CREDIT, Decimal("150"), Decimal("100"))
        receivable.refresh_from_db()

        self.assertEqual(
            Decimal(str(receivable.opening_balance)), self.BASELINE - Decimal("150")
        )

    def test_raising_a_vendor_credit_lowers_the_payable_further(self):
        payable = self.account("A/P", ChartOfAccountKindChoices.LIABILITIES)

        self.post(payable, DEBIT, Decimal("100"))
        amend_leg(payable, DEBIT, Decimal("150"), Decimal("100"))
        payable.refresh_from_db()

        self.assertEqual(
            Decimal(str(payable.opening_balance)), self.BASELINE - Decimal("150")
        )

    def test_the_old_op_moved_them_by_twice_the_delta_wrongly(self):
        """100 -> 150 moved +50 where it had to move -50."""
        receivable = self.account("A/R", ChartOfAccountKindChoices.ASSETS)
        self.post(receivable, CREDIT, Decimal("100"))
        after_post = Decimal(str(receivable.opening_balance))

        update_opening_balance(
            receivable, "update", Decimal("150"), Decimal("100")
        )
        receivable.refresh_from_db()
        old_way = Decimal(str(receivable.opening_balance))

        correct = after_post - Decimal("50")
        self.assertEqual(old_way, after_post + Decimal("50"))
        self.assertEqual(old_way - correct, Decimal("100"), "twice the delta")

    def test_amending_a_kindless_balance_continues_the_posting(self):
        """Customer and Supplier: no kind, so the posting's own operation."""
        customer = Customer.objects.create(
            company=self.company, first_name="Ada", display_name="Ada",
            opening_balance=self.BASELINE,
        )

        # Posting subtracts.
        update_opening_balance(customer, DEBIT, Decimal("100"), 0)
        customer.refresh_from_db()
        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE - Decimal("100")
        )

        amend_balance(customer, DEBIT, Decimal("150"), Decimal("100"))
        customer.refresh_from_db()
        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE - Decimal("150")
        )

    def test_lowering_a_kindless_balance_walks_it_back(self):
        customer = Customer.objects.create(
            company=self.company, first_name="Grace", display_name="Grace",
            opening_balance=self.BASELINE,
        )

        update_opening_balance(customer, DEBIT, Decimal("100"), 0)
        amend_balance(customer, DEBIT, Decimal("60"), Decimal("100"))
        customer.refresh_from_db()

        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE - Decimal("60")
        )

    def test_amend_balance_is_a_no_op_when_nothing_changed(self):
        customer = Customer.objects.create(
            company=self.company, first_name="Alan", display_name="Alan",
            opening_balance=self.BASELINE,
        )

        self.assertIsNone(
            amend_balance(customer, DEBIT, Decimal("100"), Decimal("100"))
        )
        customer.refresh_from_db()
        self.assertEqual(Decimal(str(customer.opening_balance)), self.BASELINE)

    def test_post_then_amend_equals_posting_the_new_figure(self):
        """The mirror property, on both kinded legs and every kind."""
        for side in (DEBIT, CREDIT):
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(side=side, kind=kind):
                    stepped = self.account(f"stepped {kind} {side}", kind)
                    self.post(stepped, side, Decimal("100"))
                    amend_leg(stepped, side, Decimal("150"), Decimal("100"))
                    stepped.refresh_from_db()

                    direct = self.account(f"direct {kind} {side}", kind)
                    self.post(direct, side, Decimal("150"))

                    self.assertEqual(
                        Decimal(str(stepped.opening_balance)),
                        Decimal(str(direct.opening_balance)),
                    )


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.serializers import creditnotes

        return inspect.getsource(creditnotes)

    def test_no_ledger_balance_is_amended_through_the_update_op(self):
        """`update_quantity(..., "update", ...)` is stock, not a ledger leg."""
        source = self.source().splitlines()
        offenders = []
        for i, line in enumerate(source):
            if '"update",' not in line or line.strip().startswith("#"):
                continue
            window = "\n".join(source[max(0, i - 5):i])
            if "update_quantity(" in window:
                continue
            offenders.append(i + 1)

        self.assertEqual(offenders, [], f"ledger amends still on 'update': {offenders}")

    def test_the_four_header_legs_use_the_amend_helpers(self):
        source = self.source()

        self.assertEqual(source.count("amend_balance("), 2)
        # Two header legs, plus the inventory and purchase-tax mirrors.
        self.assertGreaterEqual(source.count("amend_leg("), 4)

    def test_the_phantom_sale_tax_amend_is_gone(self):
        """It moved a balance on an account the SALE branch never posts to."""
        source = self.source()

        self.assertNotIn(
            'update_opening_balance(\n'
            '                payable_account,\n'
            '                "update",',
            source,
        )
        self.assertIn("payload carries no per-agency split", source)
