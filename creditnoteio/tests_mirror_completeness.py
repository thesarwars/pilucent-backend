"""The amend and delete mirrors of the create legs corrected in a555d998.

a555d998 made four create legs move the stored balance the way their journal
line moves. It did not touch the paths that amend or reverse those legs, and
those were written against the old, wrong direction. Correcting a posting leg
without its mirror does not leave the mirror merely stale -- it makes it wrong
in the opposite direction, so the pair now doubles the error instead of
tracking it.

Three mirrors were left behind:

    serializer item-update  inventory amend      mirrored the old ADD
    serializer note-update  PURCHASE tax amend   still wrote `.debit`, and the
                                                 create leg now writes a credit,
                                                 so an amended row carried BOTH
                                                 columns and was counted twice
    views delete            inventory reversal   comment read "Opposite of the
                                                 original credit"; it was the
                                                 opposite of the wrong thing

This is the rule the sweep keeps proving: never leave a posting leg resolving
its side from the account while its amend or reversal mirror hard-codes one.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    amend_leg,
    balance_operation_for_action,
    inverse_balance_operation,
    update_opening_balance,
)

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices


DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT


class MirrorTests(TestCase):
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
        """What the corrected create leg does."""
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()

    def reverse(self, account, side, amount):
        """What the delete path does."""
        posting_op = balance_operation_for_action(action_for_side(account.kind, side))
        update_opening_balance(
            account, inverse_balance_operation(posting_op), amount, 0
        )
        account.refresh_from_db()

    def test_posting_then_deleting_returns_inventory_to_where_it_started(self):
        """The delete mirror. It used to double the movement instead."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                inventory = self.account(f"Inventory {kind}", kind)

                self.post(inventory, CREDIT, Decimal("250"))
                self.reverse(inventory, CREDIT, Decimal("250"))

                self.assertEqual(
                    Decimal(str(inventory.opening_balance)), self.BASELINE
                )

    def test_the_old_delete_reversal_doubled_it(self):
        """Kept as the statement of what leaving the mirror behind did."""
        inventory = self.account("Inventory Asset", ChartOfAccountKindChoices.ASSETS)

        self.post(inventory, CREDIT, Decimal("250"))
        # What the view did: subtract, on the assumption the create had added.
        update_opening_balance(inventory, DEBIT, Decimal("250"), 0)
        inventory.refresh_from_db()

        self.assertEqual(
            Decimal(str(inventory.opening_balance)),
            self.BASELINE - Decimal("500"),
            "posting and deleting left inventory 500 lower, not level",
        )

    def test_amending_inventory_tracks_the_posting(self):
        """Post 100, amend to 150: the same as having posted 150."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                stepped = self.account(f"stepped {kind}", kind)
                self.post(stepped, CREDIT, Decimal("100"))
                amend_leg(stepped, CREDIT, Decimal("150"), Decimal("100"))
                stepped.refresh_from_db()

                direct = self.account(f"direct {kind}", kind)
                self.post(direct, CREDIT, Decimal("150"))

                self.assertEqual(
                    Decimal(str(stepped.opening_balance)),
                    Decimal(str(direct.opening_balance)),
                )

    def test_raising_a_returned_line_lowers_inventory_further(self):
        """A bigger credit on an asset lowers it. Both branches used to raise it."""
        inventory = self.account("Inventory Asset", ChartOfAccountKindChoices.ASSETS)

        self.post(inventory, CREDIT, Decimal("100"))
        amend_leg(inventory, CREDIT, Decimal("150"), Decimal("100"))
        inventory.refresh_from_db()

        self.assertEqual(
            Decimal(str(inventory.opening_balance)), self.BASELINE - Decimal("150")
        )

    def test_lowering_a_returned_line_raises_inventory_back(self):
        inventory = self.account("Inventory Asset", ChartOfAccountKindChoices.ASSETS)

        self.post(inventory, CREDIT, Decimal("100"))
        amend_leg(inventory, CREDIT, Decimal("60"), Decimal("100"))
        inventory.refresh_from_db()

        self.assertEqual(
            Decimal(str(inventory.opening_balance)), self.BASELINE - Decimal("60")
        )

    def test_the_purchase_tax_amend_tracks_its_credit_leg(self):
        tax = self.account("Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES)

        self.post(tax, CREDIT, Decimal("80"))
        amend_leg(tax, CREDIT, Decimal("120"), Decimal("80"))
        tax.refresh_from_db()

        self.assertEqual(
            Decimal(str(tax.opening_balance)), self.BASELINE + Decimal("120")
        )

    def test_post_amend_delete_is_a_no_op_on_every_kind(self):
        """The three paths composed. Any one of them out of step shows here."""
        for side in (DEBIT, CREDIT):
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(side=side, kind=kind):
                    account = self.account(f"round {kind} {side}", kind)

                    self.post(account, side, Decimal("100"))
                    amend_leg(account, side, Decimal("175"), Decimal("100"))
                    account.refresh_from_db()
                    self.reverse(account, side, Decimal("175"))

                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )


class CallSiteTests(TestCase):
    def serializer_source(self):
        import inspect

        from weapi.django_rest.serializers import creditnotes

        return inspect.getsource(creditnotes)

    def view_source(self):
        import inspect

        from weapi.django_rest.views import creditnotes

        return inspect.getsource(creditnotes)

    def test_the_inventory_amend_goes_through_amend_leg(self):
        self.assertIn(
            "amend_leg(\n"
            "                        inventory_account,\n"
            "                        JournalEntryConnectorKindChoices.CREDIT,",
            self.serializer_source(),
        )

    def test_the_purchase_tax_amend_writes_the_credit_column(self):
        source = self.serializer_source()

        self.assertIn("payable_journal_item.credit = new_tax_total", source)
        self.assertIn("payable_journal_item.debit = 0", source)

    def test_the_delete_reversal_derives_its_undo(self):
        """The undo must come from the stored leg, never from a literal.

        b7f02a49 did this inline in the view with `inverse_balance_operation`.
        The delete path has since been rewritten to reverse EVERY leg the line
        wrote rather than a hand-picked list, so the derivation moved into
        `reverse_item_connectors`. The property being guarded is the same one;
        only where it lives has changed.
        """
        import inspect

        from journalio.django_rest.services import journals

        view_source = self.view_source()
        self.assertIn("reverse_item_connectors(", view_source)
        self.assertNotIn("# Opposite of the original credit", view_source)
        self.assertNotIn("# Opposite of the original debit", view_source)

        self.assertIn(
            "get_migration_undo_balance_operation(account, connector.kind)",
            inspect.getsource(journals),
        )
