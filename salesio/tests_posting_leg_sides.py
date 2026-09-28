"""Every leg the unified sale engine posts, on every account kind.

`sale_posting` is the widest posting implementation in the codebase -- sale
lines, refund lines, per-line tax, auto-tax breakdown, the unattributed-tax
residual, receivable, discount, shipping and deposit -- and all thirteen legs
carried a hard-coded "addition"/"substraction".

Each is right only for the kind its author pictured, and not one of these
accounts has a guaranteed kind:

- income, cost-of-sales and inventory accounts are set per product
- tax accounts come from the agency records and the auto-tax breakdown
- A/R and Sales Discounts and Shipping Income are control accounts whose kind
  derives from an editable account type, which is what
  `repair_control_account_types` exists to correct
- the deposit charter accounts are chosen on the document itself

`_post_tax_legs` was the worst of them: it computed one action before the loop
and reused it for every tax account, so a single agency account typed as
something other than a liability posted the wrong way while the rest of the
entry looked fine.

The balance moves were already paired consistently with the literals here, so
unlike stock (180114ab) and sales (88d92a88) the stored balance never diverged
from the journal. What was wrong was which side the journal recorded.
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


DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT

# What each leg's side is, as fixed by the transaction rather than the account.
SALE_LEGS = {
    "revenue": CREDIT,
    "cost of sales": DEBIT,
    "inventory relief": CREDIT,
    "receivable": DEBIT,
    "sales discount": DEBIT,
    "shipping income": CREDIT,
    "tax collected": CREDIT,
    "deposit in": DEBIT,
}
REFUND_LEGS = {
    "revenue reversal": DEBIT,
    "inventory restored": DEBIT,
    "cost reversal": CREDIT,
    "tax refunded": DEBIT,
    "deposit out": CREDIT,
}


class PostingLegSideTests(TestCase):
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

    def test_every_leg_lands_on_its_side_for_every_kind(self):
        for name, side in {**SALE_LEGS, **REFUND_LEGS}.items():
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(leg=name, kind=kind):
                    account = self.account(f"{name} {kind}", kind)
                    action = action_for_side(account.kind, side)
                    self.assertEqual(self.side_of(account, action), side)

    def test_a_sale_and_its_refund_net_to_zero(self):
        """Each refund leg is the mirror of the sale leg it reverses."""
        pairs = [
            ("revenue", "revenue reversal"),
            ("inventory relief", "inventory restored"),
            ("cost of sales", "cost reversal"),
            ("tax collected", "tax refunded"),
            ("deposit in", "deposit out"),
        ]
        for sale_leg, refund_leg in pairs:
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(pair=(sale_leg, refund_leg), kind=kind):
                    account = self.account(f"{sale_leg}/{refund_leg} {kind}", kind)

                    for side in (SALE_LEGS[sale_leg], REFUND_LEGS[refund_leg]):
                        action = action_for_side(account.kind, side)
                        update_opening_balance(
                            account,
                            balance_operation_for_action(action),
                            self.AMOUNT,
                            0,
                        )
                    account.refresh_from_db()

                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )

    def test_the_sale_entry_balances_whatever_the_kinds(self):
        """Debits equal credits across a whole sale, on any mix of kinds.

        The literals made this hold only where every account happened to carry
        the kind its call site assumed.
        """
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                debits = credits = Decimal("0.00")
                for name, side in SALE_LEGS.items():
                    account = self.account(f"{name} all-{kind}", kind)
                    landed = self.side_of(
                        account, action_for_side(account.kind, side)
                    )
                    if landed == DEBIT:
                        debits += self.AMOUNT
                    else:
                        credits += self.AMOUNT

                expected_debits = sum(
                    self.AMOUNT for s in SALE_LEGS.values() if s == DEBIT
                )
                self.assertEqual(debits, expected_debits)
                self.assertEqual(debits + credits, self.AMOUNT * len(SALE_LEGS))

    def test_a_tax_account_typed_as_an_asset_still_credits_on_a_sale(self):
        """The `_post_tax_legs` case: one shared action for many accounts."""
        liability = self.account("Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES)
        misconfigured = self.account("State Tax", ChartOfAccountKindChoices.ASSETS)

        for account in (liability, misconfigured):
            action = action_for_side(account.kind, CREDIT)
            self.assertEqual(self.side_of(account, action), CREDIT)

        # The shared literal landed them on opposite sides.
        self.assertNotEqual(
            self.side_of(liability, "addition"),
            self.side_of(misconfigured, "addition"),
        )


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.helpers import sale_posting

        return inspect.getsource(sale_posting)

    def test_no_journal_leg_carries_a_hard_coded_action(self):
        """`update_quantity` also takes "addition", and is not a journal leg."""
        for line in self.source().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "update_quantity" in stripped:
                continue
            self.assertNotIn(
                '"addition",', stripped, f"hard-coded action in: {stripped}"
            )
            self.assertNotIn(
                '"substraction",', stripped, f"hard-coded action in: {stripped}"
            )

    def test_the_tax_action_is_resolved_inside_the_loop(self):
        """It was computed once before the loop and shared by every account."""
        source = self.source()

        self.assertNotIn('action = "substraction" if is_refund else "addition"', source)
        self.assertIn("tax_action = action_for_side(account.kind, tax_side)", source)

    def test_every_leg_resolves_from_a_side(self):
        source = self.source()

        # Thirteen posting legs plus the reversal helper, which already
        # derived its action from the stored connector kind.
        self.assertEqual(source.count("action_for_side("), 14)
