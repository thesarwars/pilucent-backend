"""Deleting a credit-note line left the entry short by exactly that line.

Two defects, both structural.

**The header leg was never touched.** A credit note posts its receivable (or
payable) once for the whole document. Removing a line deleted the line's own legs
and left the header leg at its original figure, so the entry was permanently
short by the line total -- while `journal_entry.amount` was decremented, making
the header look right. Nothing raised, because `assert_entry_balances` only runs
where entries are written and this path never wrote one.

**Legs outside a hand-picked list were deleted without reversal.** The path
reversed income, product asset and cost of sales for a sale line, and inventory
and the charter account for a purchase line. Anything else a line had posted --
a tax leg, an account reached through a different product configuration -- was
not reversed, and the CASCADE on `JournalEntryConnector.credit_note_item` then
removed it silently. The stored balance kept the movement while the line
explaining it was gone.

That list could never be right in general: which accounts a line touches depends
on the product's configuration, its tax groups and what the request supplied.
`reverse_item_connectors` enumerates the legs that exist instead, and derives
each undo from the leg's own stored kind -- so it also unwinds rows written
before the sides were corrected, which a hard-coded undo gets backwards.
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


class ReverseItemConnectorsTests(TestCase):
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

    def entry(self):
        return JournalEntry.objects.create(
            company=self.company,
            entry_number="JE-TEST",
            amount=Decimal("0"),
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.CREDIT_NOTE,
        )

    def post_leg(self, entry, account, side, amount):
        """Post a leg the way the corrected create paths do."""
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()
        return JournalEntryConnector.objects.create(
            journal=entry,
            account=account,
            kind=side,
            debit=amount if side == DEBIT else 0,
            credit=amount if side == CREDIT else 0,
            total=amount,
            last_balance=account.opening_balance,
        )

    def test_reversing_a_leg_returns_the_balance_to_where_it_started(self):
        for side in (DEBIT, CREDIT):
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(side=side, kind=kind):
                    account = self.account(f"A {kind} {side}", kind)
                    entry = self.entry()
                    self.post_leg(entry, account, side, Decimal("250"))

                    reverse_item_connectors(
                        entry.journalentryconnector_set.all()
                    )

                    account.refresh_from_db()
                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )

    def test_it_removes_the_rows(self):
        account = self.account("Inventory", ChartOfAccountKindChoices.ASSETS)
        entry = self.entry()
        self.post_leg(entry, account, CREDIT, Decimal("100"))

        self.assertEqual(entry.journalentryconnector_set.count(), 1)
        reversed_legs = reverse_item_connectors(
            entry.journalentryconnector_set.all()
        )

        self.assertEqual(reversed_legs, 1)
        self.assertEqual(entry.journalentryconnector_set.count(), 0)

    def test_it_reverses_every_leg_not_a_chosen_few(self):
        """The point of the change: coverage does not depend on a list."""
        entry = self.entry()
        accounts = [
            (self.account("Income", ChartOfAccountKindChoices.INCOMES), DEBIT),
            (self.account("Inventory", ChartOfAccountKindChoices.ASSETS), DEBIT),
            (self.account("COGS", ChartOfAccountKindChoices.EXPENSES), CREDIT),
            (self.account("State Tax", ChartOfAccountKindChoices.LIABILITIES), DEBIT),
            (self.account("Odd One", ChartOfAccountKindChoices.EQUITIES), CREDIT),
        ]
        for account, side in accounts:
            self.post_leg(entry, account, side, Decimal("40"))

        reversed_legs = reverse_item_connectors(
            entry.journalentryconnector_set.all()
        )

        self.assertEqual(reversed_legs, len(accounts))
        for account, _side in accounts:
            account.refresh_from_db()
            with self.subTest(account=account.title):
                self.assertEqual(
                    Decimal(str(account.opening_balance)), self.BASELINE
                )

    def test_a_leg_with_no_amount_is_skipped(self):
        account = self.account("Empty", ChartOfAccountKindChoices.ASSETS)
        entry = self.entry()
        JournalEntryConnector.objects.create(
            journal=entry, account=account, kind=CREDIT,
            debit=0, credit=0, total=0,
            last_balance=account.opening_balance,
        )

        self.assertEqual(
            reverse_item_connectors(entry.journalentryconnector_set.all()), 0
        )
        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)

    def test_it_unwinds_rows_written_before_the_sides_were_corrected(self):
        """The undo comes from the leg's stored kind, not from a literal.

        A hard-coded undo reverses what the author assumed was written. Rows
        posted before the create legs were corrected carry the other side, and
        those are exactly the rows a delete is most likely to meet.
        """
        inventory = self.account("Inventory", ChartOfAccountKindChoices.ASSETS)
        entry = self.entry()

        # A row as the OLD code would have left it: a debit on inventory.
        update_opening_balance(inventory, CREDIT, Decimal("250"), 0)
        inventory.refresh_from_db()
        raised = Decimal(str(inventory.opening_balance))
        JournalEntryConnector.objects.create(
            journal=entry, account=inventory, kind=DEBIT,
            debit=Decimal("250"), credit=0, total=Decimal("250"),
            last_balance=raised,
        )

        reverse_item_connectors(entry.journalentryconnector_set.all())

        inventory.refresh_from_db()
        self.assertEqual(
            Decimal(str(inventory.opening_balance)),
            raised - Decimal("250"),
            "a debit leg is undone by subtracting, whatever the create did",
        )


class DeletePathCallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.views import creditnotes

        return inspect.getsource(creditnotes)

    def test_the_delete_path_reverses_every_leg(self):
        source = self.source()

        self.assertIn("reverse_item_connectors(", source)
        # The hand-picked per-account reversal blocks are gone.
        self.assertNotIn("income_account_journals", source)
        self.assertNotIn("cost_of_goods_journals", source)
        self.assertNotIn("charter_account_journals", source)

    def test_the_delete_path_reduces_the_header_leg(self):
        source = self.source()

        self.assertIn("credit_note_item__isnull=True", source)
        self.assertIn("amend_leg(header_account, header_side", source)

    def test_the_delete_path_checks_the_entry_afterwards(self):
        """It never wrote through the posting service, so nothing checked it."""
        self.assertIn("assert_entry_balances(journal_entry)", self.source())

    def test_the_header_side_matches_the_document_kind(self):
        source = self.source()

        self.assertIn(
            'header_title = "Accounts Receivable (A/R)"\n'
            "                header_side = JournalEntryConnectorKindChoices.CREDIT",
            source,
        )
        self.assertIn(
            'header_title = "Accounts Payable (A/P)"\n'
            "                header_side = JournalEntryConnectorKindChoices.DEBIT",
            source,
        )


class PartyBalanceOnDeleteTests(TestCase):
    """The control account and the subledger have to move together.

    `create` moves `customer.opening_balance` alongside the A/R leg. The
    header-leg reduction that landed in 33f27fb8 replaced an unbalanced entry
    with a balanced one but left that party balance stale -- so A/R reported one
    figure and the sum of customer balances reported another. A quieter fault of
    the same kind as the one it fixed.
    """

    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def test_removing_a_line_gives_the_party_back_its_share(self):
        from common.django_rest.helpers.balance_helpers import amend_balance
        from customerio.models import Customer

        customer = Customer.objects.create(
            company=self.company, first_name="Ada", display_name="Ada",
            opening_balance=self.BASELINE,
        )

        # Posting a 300 note subtracts 300.
        update_opening_balance(customer, DEBIT, Decimal("300"), 0)
        customer.refresh_from_db()
        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE - Decimal("300")
        )

        # Removing a 100 line leaves a 200 note.
        amend_balance(customer, DEBIT, Decimal("200"), Decimal("300"))
        customer.refresh_from_db()

        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE - Decimal("200")
        )

    def test_removing_the_last_line_returns_the_party_to_baseline(self):
        from common.django_rest.helpers.balance_helpers import amend_balance
        from customerio.models import Customer

        customer = Customer.objects.create(
            company=self.company, first_name="Grace", display_name="Grace",
            opening_balance=self.BASELINE,
        )

        update_opening_balance(customer, DEBIT, Decimal("300"), 0)
        amend_balance(customer, DEBIT, Decimal("0"), Decimal("300"))
        customer.refresh_from_db()

        self.assertEqual(Decimal(str(customer.opening_balance)), self.BASELINE)

    def test_the_delete_path_moves_it(self):
        import inspect

        from weapi.django_rest.views import creditnotes

        source = inspect.getsource(creditnotes)
        self.assertIn("amend_balance(", source)
        self.assertIn("credit_note.supplier", source)
