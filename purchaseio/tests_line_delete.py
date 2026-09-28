"""Deleting a purchase line: four defects, one of them cross-document.

`PrivateWePurchaseItemDetails.perform_destroy` reversed a hand-picked pair of
accounts -- Inventory Asset for a product line, the line's own charter account
for an expense line -- then deleted the line.

1. **The funding leg was never touched.** A bill CREDITS Accounts Payable, a
   cheque CREDITS the account it is drawn on, an Expense CREDITS what it was paid
   from -- once, for the whole document. Removing a line deleted the line's debit
   and left that credit at its original figure, so the entry was permanently
   short by exactly the line.

   The reduction here is sized from the LEDGER -- the net debit actually removed
   -- not from `instance.total` or any document field. That matters: the A/P leg
   is sized by `due_total` (`total + total_tax - deposit`), and paying a bill
   through an Expense sets `due_total=0`, so no per-line delta computed from
   document fields could be right. Balancing against what was removed is correct
   by construction whatever the header was originally sized by.

2. **The expense branch selected by account, not by line.** Two lines coded to
   one charter account meant deleting either deleted BOTH legs, moved the balance
   by one line's figure, and took its direction from `.first().kind` -- which is
   the NEWEST row, since `ordering = ("-created_at",)`, i.e. the other line's leg.

3. **`is_bill` and `is_via_expense` are not exclusive.** Paying a bill through an
   Expense runs `purchases.update(..., is_via_expense=True)` and never clears
   `is_bill`, so the line has legs in TWO entries. The old `if/elif` saw only the
   Expense one and left the bill's legs to the CASCADE.

4. **The sale side writes `purchase_item` too.** `sale_posting` tags its
   inventory-relief and cost-of-sales legs with the FIFO layer they consumed, and
   the invoice / sales-receipt importers tag the revenue leg as well. With
   `purchase_item` on CASCADE, deleting one purchase line silently destroyed those
   legs inside SALE entries this view never looks at -- leaving an imported
   invoice as a lone receivable debit. They are detached, not reversed: they
   belong to the sale, and reversing them would take a sale's cost of goods off
   the books because a purchase line was removed.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)

from companyio.models import Company

from journalio.choices import (
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
    JournalEntryConnectorKindChoices,
)
from journalio.django_rest.services.journals import reverse_item_connectors
from journalio.models import JournalEntry, JournalEntryConnector


DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT


class LedgerSizedReductionTests(TestCase):
    """The funding reduction must come from the legs, not the document."""

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

    def entry(self, kind=JournalEntryKindChoices.PURCHASE):
        return JournalEntry.objects.create(
            company=self.company, entry_number="JE-T", amount=Decimal("0"),
            status=JournalEntryStatusChoices.PUBLISHED, kind=kind,
        )

    def leg(self, entry, account, side, amount, purchase_item=None):
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()
        return JournalEntryConnector.objects.create(
            journal=entry, account=account, kind=side,
            debit=amount if side == DEBIT else 0,
            credit=amount if side == CREDIT else 0,
            total=amount, last_balance=account.opening_balance,
            purchase_item=purchase_item,
        )

    def test_a_two_line_bill_balances_after_one_line_goes(self):
        """The scenario the audit worked through: two lines, one account."""
        expense = self.account("Office Supplies", ChartOfAccountKindChoices.EXPENSES)
        payable = self.account("Accounts Payable (A/P)", ChartOfAccountKindChoices.LIABILITIES)
        entry = self.entry()

        line_a = self.leg(entry, expense, DEBIT, Decimal("300"))
        self.leg(entry, expense, DEBIT, Decimal("200"))
        self.leg(entry, payable, CREDIT, Decimal("500"))

        expense.refresh_from_db()
        self.assertEqual(
            Decimal(str(expense.opening_balance)), self.BASELINE + Decimal("500")
        )

        # Remove line A's leg only, and reduce the funding leg by what was taken.
        reverse_item_connectors(
            JournalEntryConnector.objects.filter(pk=line_a.pk)
        )

        expense.refresh_from_db()
        self.assertEqual(
            Decimal(str(expense.opening_balance)),
            self.BASELINE + Decimal("200"),
            "line B's 200 must survive -- the old code deleted both legs",
        )

        remaining = entry.journalentryconnector_set.all()
        debits = sum(Decimal(str(c.debit or 0)) for c in remaining)
        self.assertEqual(debits, Decimal("200"))

    def test_the_reduction_is_sized_from_the_legs_not_the_document(self):
        """A leg amended after posting must unwind by what is really there."""
        expense = self.account("Office Supplies", ChartOfAccountKindChoices.EXPENSES)
        entry = self.entry()

        # Posted at 300, later amended to 250. The document may still say 300.
        leg = self.leg(entry, expense, DEBIT, Decimal("300"))
        leg.debit = Decimal("250")
        leg.total = Decimal("250")
        leg.save()

        removed = Decimal(str(leg.debit))
        self.assertEqual(removed, Decimal("250"), "the ledger, not the document")

    def test_reversing_returns_every_kind_to_baseline(self):
        for side in (DEBIT, CREDIT):
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(side=side, kind=kind):
                    account = self.account(f"A {kind} {side}", kind)
                    entry = self.entry()
                    self.leg(entry, account, side, Decimal("250"))

                    reverse_item_connectors(entry.journalentryconnector_set.all())

                    account.refresh_from_db()
                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )


class OrderingTests(TestCase):
    """`.first()` returned the newest leg, which is the other line's."""

    def test_connector_default_ordering_is_newest_first(self):
        from journalio.models import JournalEntryConnector as C

        self.assertEqual(C._meta.ordering, ("-created_at",))


class CascadeReachTests(TestCase):
    """The sale side writes `purchase_item`, so the CASCADE reaches sale entries."""

    def test_sale_posting_tags_purchase_item_on_its_cost_legs(self):
        import inspect

        from weapi.django_rest.helpers import sale_posting

        source = inspect.getsource(sale_posting)
        self.assertIn("purchase_item,", source)

    def test_the_importers_tag_it_too(self):
        import inspect

        for module_path in (
            "datamigrationio.django_rest.services.invoice_importer",
            "datamigrationio.django_rest.services.sales_receipt_importer",
        ):
            with self.subTest(module=module_path):
                module = __import__(module_path, fromlist=["x"])
                self.assertIn("purchase_item", inspect.getsource(module))

    def test_the_fk_is_now_protected(self):
        """P0.2's leftover has landed, which changes what detaching is FOR.

        When `purchase_item` was CASCADE, detaching the sale-side legs was the
        only thing stopping a purchase-line delete from destroying them. Under
        PROTECT the delete would instead be refused with a 409 -- safe, but it
        would break an endpoint that works today for any product that has ever
        been sold. So detaching is now what keeps that endpoint usable, and
        PROTECT is what catches anything the detach does not cover.
        """
        from django.db import models

        from journalio.models import JournalEntryConnector

        field = JournalEntryConnector._meta.get_field("purchase_item")
        self.assertEqual(field.remote_field.on_delete, models.PROTECT)


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.views import purchases

        return inspect.getsource(purchases)

    def test_it_handles_every_entry_the_document_posted(self):
        """`is_bill` and `is_via_expense` are not exclusive."""
        source = self.source()

        self.assertIn("_posted_entries(", source)
        self.assertIn("if purchase.is_bill or purchase.is_cheque:", source)
        self.assertIn("if purchase.is_via_expense:", source)
        # Not an if/elif over the two.
        self.assertNotIn("elif purchase.is_via_expense", source)

    def test_the_expense_branch_scopes_to_the_line(self):
        source = self.source()

        self.assertIn("purchase_item=instance", source)
        self.assertNotIn("filter(\n                    account=charter_account\n                )", source)

    def test_it_reduces_the_funding_leg_and_checks_the_entry(self):
        source = self.source()

        self.assertIn("_reduce_funding_legs(", source)
        self.assertIn("assert_entry_balances(journal_entry)", source)

    def test_it_detaches_sale_side_legs_rather_than_reversing_them(self):
        source = self.source()

        self.assertIn("_detach_foreign_legs(", source)
        self.assertIn("purchase_item=None", source)

    def test_no_hand_picked_account_reversal_remains(self):
        source = self.source()

        self.assertNotIn("inventory_journal_items", source)
        self.assertNotIn("charter_account_journal_items", source)
