"""Reversing a credit note must leave nothing behind, including what has no leg.

First half of moving credit notes onto reverse-and-repost, the pattern
`sale_posting` already uses. `PrivateCreditNoteItemDetailsSerializer.update` is
~400 lines of patch-in-place carrying 26 defects that are wrong on the
conventional account kinds; the sale side reached the same point and its fix
records why patching could not work -- "it could only find the connectors it
recognised, and anything it missed stayed in the ledger."

A reversal has to undo four things, and only the first is visible to anything
that walks journal rows:

    journal connectors      every leg's effect on its account's stored balance
    customer / supplier     moved alongside A/R or A/P, with no journal row
    product quantity        SALE returns goods to stock, PURCHASE removes them
    purchase item quantity  a SALE note refills the FIFO layer it drew from

The last three are exactly what a connector-walk cannot see, which is the other
reason the old approach was never going to be complete.
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

from creditnoteio.choices import CreditNoteKindChoices, CreditNoteItemStatusChoices
from creditnoteio.models import CreditNote, CreditNoteItem

from customerio.models import Customer

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.helpers.credit_note_posting import (
    _reverse_party_balance,
    reverse_credit_note_postings,
)


DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT


class ReversalTests(TestCase):
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

    def credit_note(self, kind=CreditNoteKindChoices.SALE, total="0", customer=None):
        return CreditNote.objects.create(
            company=self.company, kind=kind,
            total=Decimal(str(total)), customer=customer,
        )

    def entry(self, credit_note):
        return JournalEntry.objects.create(
            company=self.company, entry_number="JE-CN", amount=Decimal("0"),
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.CREDIT_NOTE,
            credit_note=credit_note,
        )

    def post_leg(self, entry, account, side, amount):
        """Post a leg the way the corrected create path does."""
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
        )

    def test_every_account_returns_to_its_starting_balance(self):
        note = self.credit_note()
        entry = self.entry(note)
        accounts = [
            (self.account("Income", ChartOfAccountKindChoices.INCOMES), DEBIT),
            (self.account("Inventory", ChartOfAccountKindChoices.ASSETS), DEBIT),
            (self.account("COGS", ChartOfAccountKindChoices.EXPENSES), CREDIT),
            (self.account("A/R", ChartOfAccountKindChoices.ASSETS), CREDIT),
            (self.account("Tax", ChartOfAccountKindChoices.LIABILITIES), DEBIT),
        ]
        for account, side in accounts:
            self.post_leg(entry, account, side, Decimal("40"))

        summary = reverse_credit_note_postings(note)

        self.assertEqual(summary["connectors_reversed"], len(accounts))
        for account, _side in accounts:
            account.refresh_from_db()
            with self.subTest(account=account.title):
                self.assertEqual(
                    Decimal(str(account.opening_balance)), self.BASELINE
                )

    def test_the_journal_entry_is_removed(self):
        note = self.credit_note()
        entry = self.entry(note)
        self.post_leg(
            entry,
            self.account("A/R", ChartOfAccountKindChoices.ASSETS),
            CREDIT,
            Decimal("50"),
        )

        summary = reverse_credit_note_postings(note)

        self.assertEqual(summary["journal_entries_deleted"], 1)
        self.assertFalse(JournalEntry.objects.filter(pk=entry.pk).exists())
        self.assertFalse(
            JournalEntryConnector.objects.filter(journal_id=entry.pk).exists()
        )

    def test_it_unwinds_rows_written_before_the_sides_were_corrected(self):
        """The undo comes from the leg's stored kind, not from a literal.

        Most of what is on the books was posted before the create-path sides were
        fixed, so a reversal that assumed today's sides would be backwards on
        exactly the rows it will actually meet.
        """
        inventory = self.account("Inventory", ChartOfAccountKindChoices.ASSETS)
        note = self.credit_note()
        entry = self.entry(note)

        # A row as the OLD create path left it: a debit on inventory.
        update_opening_balance(inventory, CREDIT, Decimal("60"), 0)
        inventory.refresh_from_db()
        raised = Decimal(str(inventory.opening_balance))
        JournalEntryConnector.objects.create(
            journal=entry, account=inventory, kind=DEBIT,
            debit=Decimal("60"), credit=0, total=Decimal("60"),
            last_balance=raised,
        )

        reverse_credit_note_postings(note)

        inventory.refresh_from_db()
        self.assertEqual(
            Decimal(str(inventory.opening_balance)), raised - Decimal("60")
        )

    def test_a_zero_amount_leg_is_skipped(self):
        note = self.credit_note()
        entry = self.entry(note)
        account = self.account("Empty", ChartOfAccountKindChoices.ASSETS)
        JournalEntryConnector.objects.create(
            journal=entry, account=account, kind=CREDIT,
            debit=0, credit=0, total=0, last_balance=account.opening_balance,
        )

        summary = reverse_credit_note_postings(note)

        self.assertEqual(summary["connectors_reversed"], 0)
        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)


class PartyBalanceTests(ReversalTests):
    """The customer/supplier balance has no journal row, so nothing else finds it."""

    def test_a_sale_note_gives_the_customer_back_what_it_took(self):
        customer = Customer.objects.create(
            company=self.company, first_name="Ada", display_name="Ada",
            opening_balance=self.BASELINE,
        )
        note = self.credit_note(total="250", customer=customer)

        # Posting subtracts.
        update_opening_balance(customer, DEBIT, Decimal("250"), 0)
        customer.refresh_from_db()
        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE - Decimal("250")
        )

        reversed_amount = _reverse_party_balance(note)

        customer.refresh_from_db()
        self.assertEqual(reversed_amount, Decimal("250"))
        self.assertEqual(Decimal(str(customer.opening_balance)), self.BASELINE)

    def test_a_note_with_no_party_is_a_no_op(self):
        note = self.credit_note(total="250")

        self.assertEqual(_reverse_party_balance(note), Decimal("0.00"))

    def test_a_zero_total_note_is_a_no_op(self):
        customer = Customer.objects.create(
            company=self.company, first_name="Grace", display_name="Grace",
            opening_balance=self.BASELINE,
        )
        note = self.credit_note(total="0", customer=customer)

        self.assertEqual(_reverse_party_balance(note), Decimal("0.00"))
        customer.refresh_from_db()
        self.assertEqual(Decimal(str(customer.opening_balance)), self.BASELINE)

    def test_the_summary_reports_it(self):
        customer = Customer.objects.create(
            company=self.company, first_name="Alan", display_name="Alan",
            opening_balance=self.BASELINE,
        )
        note = self.credit_note(total="120", customer=customer)

        summary = reverse_credit_note_postings(note)

        self.assertEqual(summary["party_balance_reversed"], Decimal("120"))


class QuantityRestoreTests(ReversalTests):
    """Stock is the half a connector-walk cannot see."""

    def line(self, note, product=None, quantity=3):
        return CreditNoteItem.objects.create(
            credit_note=note, product=product, quantity=quantity,
            total=Decimal("0"), status=CreditNoteItemStatusChoices.ACTIVE,
        )

    def test_a_line_with_no_product_is_skipped(self):
        note = self.credit_note()
        self.line(note, product=None)

        summary = reverse_credit_note_postings(note)

        self.assertEqual(summary["units_restored"], 0)

    def test_a_zero_quantity_line_is_skipped(self):
        note = self.credit_note()
        self.line(note, product=None, quantity=0)

        summary = reverse_credit_note_postings(note)

        self.assertEqual(summary["units_restored"], 0)

    def test_restoring_can_be_switched_off(self):
        """For a caller that has already decided the goods are not moving."""
        note = self.credit_note()

        summary = reverse_credit_note_postings(note, restore_quantities=False)

        self.assertEqual(summary["units_restored"], 0)
        self.assertEqual(summary["layers_restored"], 0)
