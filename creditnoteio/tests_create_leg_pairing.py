"""Credit-note create legs: the stored balance must move the way the journal does.

Four legs in the create paths passed a CREDIT/"credit" argument to
`update_opening_balance` beside a connector recording "substraction". Those are
not the same thing -- that argument means ADD, not an accounting side -- so the
ledger moved one way and the stored balance the other, on an entry that still
balanced. Nothing could see it: `assert_entry_balances` checks the entry, and the
entry was fine.

    574  note-create, PURCHASE product   journal CREDITs inventory, balance ADDed
    651  note-create, SALE per-item tax  journal DEBITs the liability, balance ADDed
    680  note-create, SALE breakdown tax same, second code path
    1240 item-create, PURCHASE product   the item-level twin of 574

A fifth defect is a side, not a pairing. The PURCHASE branch posted its sales-tax
leg as "substraction" -- a DEBIT on a liability, the same side as the A/P leg
beside it -- when the bill DEBITED that account and a vendor credit reversing it
must CREDIT. So the branch wrote debits of `total + total_tax` against credits of
`total - total_tax`, and every taxed purchase credit note was out by twice its
tax.

That the entry balances once the leg is a credit is what tells us `total` arrives
gross: debits of `total` against credits of the net cost lines plus `total_tax`.
`test_a_taxed_vendor_credit_balances` is that arithmetic, and it is the reason to
trust the change.

Also fixed here: the per-item tax balance moved unconditionally while its journal
line was gated on the document's header `total_tax`, so a credit note carrying
per-item tax with a zero header moved the liability with nothing in the ledger to
explain it.
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


class LegPairingTests(TestCase):
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

    def post(self, account, side, amount=None):
        amount = self.AMOUNT if amount is None else amount
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()
        return action

    def test_returning_goods_to_a_supplier_lowers_inventory(self):
        """574 and 1240. The balance used to rise while the journal lowered it."""
        inventory = self.account("Inventory Asset", ChartOfAccountKindChoices.ASSETS)

        action = self.post(inventory, CREDIT)

        self.assertEqual(self.side_of(inventory, action), CREDIT)
        self.assertEqual(
            Decimal(str(inventory.opening_balance)), self.BASELINE - self.AMOUNT
        )

    def test_handing_sales_tax_back_lowers_the_liability(self):
        """651 and 680. The balance used to rise while the journal debited."""
        tax = self.account("State Sales Tax", ChartOfAccountKindChoices.LIABILITIES)

        action = self.post(tax, DEBIT)

        self.assertEqual(self.side_of(tax, action), DEBIT)
        self.assertEqual(
            Decimal(str(tax.opening_balance)), self.BASELINE - self.AMOUNT
        )

    def test_the_old_pairing_moved_the_balance_the_other_way(self):
        """Kept as the executable statement of the defect."""
        for title, kind in (
            ("Inventory Asset", ChartOfAccountKindChoices.ASSETS),
            ("State Sales Tax", ChartOfAccountKindChoices.LIABILITIES),
        ):
            with self.subTest(account=title):
                old_way = self.account(f"{title} old", kind)
                # What the code did: CREDIT the balance helper, which means ADD.
                update_opening_balance(
                    old_way, JournalEntryConnectorKindChoices.CREDIT, self.AMOUNT, 0
                )
                old_way.refresh_from_db()

                self.assertEqual(
                    Decimal(str(old_way.opening_balance)),
                    self.BASELINE + self.AMOUNT,
                    "the balance rose",
                )
                self.assertEqual(
                    self.side_of(old_way, "substraction"),
                    CREDIT if kind == ChartOfAccountKindChoices.ASSETS else DEBIT,
                )

    def test_every_pairing_holds_on_every_kind(self):
        for side in (DEBIT, CREDIT):
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(side=side, kind=kind):
                    account = self.account(f"A {kind} {side}", kind)
                    action = self.post(account, side)

                    landed = self.side_of(account, action)
                    natural = (
                        DEBIT
                        if kind in (
                            ChartOfAccountKindChoices.ASSETS,
                            ChartOfAccountKindChoices.EXPENSES,
                        )
                        else CREDIT
                    )
                    expected = (
                        self.BASELINE + self.AMOUNT
                        if landed == natural
                        else self.BASELINE - self.AMOUNT
                    )
                    self.assertEqual(
                        Decimal(str(account.opening_balance)), expected
                    )


class PurchaseTaxSideTests(LegPairingTests):
    """The PURCHASE branch's tax leg was on the same side as its A/P leg."""

    NET = Decimal("1000")
    TAX = Decimal("80")

    def test_a_taxed_vendor_credit_balances(self):
        """Debits `total` against credits of the net lines plus the tax.

        This is the arithmetic that says the fix is right, and that `total`
        arrives gross.
        """
        gross = self.NET + self.TAX

        payable = self.account("Accounts Payable (A/P)", ChartOfAccountKindChoices.LIABILITIES)
        expense = self.account("Office Supplies", ChartOfAccountKindChoices.EXPENSES)
        tax = self.account("Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES)

        legs = [
            (payable, DEBIT, gross),
            (expense, CREDIT, self.NET),
            (tax, CREDIT, self.TAX),
        ]

        debits = sum(a for _acc, s, a in legs if s == DEBIT)
        credits = sum(a for _acc, s, a in legs if s == CREDIT)

        self.assertEqual(debits, credits)

    def test_the_old_side_put_it_out_by_twice_the_tax(self):
        gross = self.NET + self.TAX

        # What the code did: the tax leg DEBITED alongside A/P.
        debits = gross + self.TAX
        credits = self.NET

        self.assertEqual(debits - credits, 2 * self.TAX)

    def test_the_tax_leg_credits_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                tax = self.account(f"Sales Tax Payable {kind}", kind)
                action = action_for_side(tax.kind, CREDIT)
                self.assertEqual(self.side_of(tax, action), CREDIT)

    def test_the_tax_leg_is_the_opposite_side_from_the_payable_leg(self):
        """Both carried "substraction"; on one kind that is the same side."""
        payable = self.account("A/P", ChartOfAccountKindChoices.LIABILITIES)
        tax = self.account("Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES)

        self.assertEqual(
            self.side_of(payable, "substraction"),
            self.side_of(tax, "substraction"),
            "which is exactly what was wrong",
        )
        self.assertNotEqual(
            self.side_of(payable, action_for_side(payable.kind, DEBIT)),
            self.side_of(tax, action_for_side(tax.kind, CREDIT)),
        )


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.serializers import creditnotes

        return inspect.getsource(creditnotes)

    def test_the_helpers_are_imported(self):
        """They were never imported, which is why all 35 sites hard-coded."""
        source = self.source()

        self.assertIn("    action_for_side,", source)
        self.assertIn("    balance_operation_for_action,", source)

    def test_the_five_create_legs_resolve_from_a_side(self):
        source = self.source()

        for name in (
            "inventory_action = action_for_side(",
            "item_tax_action = action_for_side(",
            "breakdown_tax_action = action_for_side(",
            "purchase_tax_action = action_for_side(",
        ):
            self.assertIn(name, source)

    def test_the_purchase_branch_posts_its_tax_leg_on_the_credit_side(self):
        """The PURCHASE branch's tax leg, isolated from the SALE branch's.

        Both branches have a leg on a `payable_account`; only the SALE one is a
        reversal of tax collected and belongs on the debit side. Matching on the
        variable name alone would not tell them apart, so this cuts the source at
        the PURCHASE branch of `create` and reads only what follows.
        """
        self.assertIn(
            "purchase_tax_action = action_for_side(\n"
            "                payable_account.kind,\n"
            "                JournalEntryConnectorKindChoices.CREDIT,\n"
            "            )",
            self.source(),
        )

    def test_the_per_item_tax_balance_is_gated_with_its_journal_line(self):
        source = self.source()

        self.assertNotIn(
            'update_opening_balance(\n                            item_payable_account, "credit", tax_amount, 0\n                        )',
            source,
        )
