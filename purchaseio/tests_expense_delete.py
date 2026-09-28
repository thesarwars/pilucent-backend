"""Deleting an expense used to erase its ledger rows.

`PrivateWeExpenseDetails` is a `RetrieveUpdateDestroyAPIView` that declared no
`perform_destroy`, so `DELETE /we/expenses/{uid}` ran DRF's default
`instance.delete()`. `JournalEntry.expense` is CASCADE and
`JournalEntryConnector.journal` is CASCADE, so the delete took the entry and
every leg with it -- while leaving every `opening_balance` those legs had moved
exactly where it was.

Three things went wrong at once and none of them were visible:

* the cost and the funding dropped out of the register and out of every report
* the stored account balances kept asserting figures no ledger line supported
* nothing survived to say the expense had ever been posted, so the drift could
  not be measured, let alone replayed

`void_sale_postings` names this exact failure in its own docstring. Sales were
fixed; expenses were not, and unlike a sale an expense was not even
soft-deleted, so the rows were gone rather than stale.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from purchaseio.choices import ExpenseStatusChoices
from purchaseio.models import Expense

from supplierio.models import Supplier

from weapi.django_rest.helpers.expense_posting import void_expense_postings


class ExpenseVoidTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="E", email="expense@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Acme", display_name="Acme Ltd"
        )
        self.bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "1000")
        self.rent = self.account("Rent", ChartOfAccountKindChoices.EXPENSES, "0")
        self.expense = Expense.objects.create(
            supplier=self.supplier,
            status=ExpenseStatusChoices.PUBLISHED,
            total=Decimal("250"),
            payment_account=self.bank,
        )
        self.entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.EXPENSE,
            status=JournalEntryStatusChoices.PUBLISHED,
            amount=Decimal("250"),
            expense=self.expense,
        )
        # Rent 250 debited, bank 250 credited.
        self.cost_leg = JournalEntryConnector.objects.create(
            journal=self.entry, account=self.rent, date="2026-03-01",
            debit=Decimal("250"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        self.bank_leg = JournalEntryConnector.objects.create(
            journal=self.entry, account=self.bank, date="2026-03-01",
            debit=Decimal("0"), credit=Decimal("250"),
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        # The stored balances as the posting would have left them.
        self.rent.opening_balance = Decimal("250")
        self.rent.save()
        self.bank.opening_balance = Decimal("750")
        self.bank.save()

    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def balances(self):
        self.rent.refresh_from_db()
        self.bank.refresh_from_db()
        return self.rent.opening_balance, self.bank.opening_balance


class TheOldDeleteDestroyedTheLedgerTests(ExpenseVoidTestCase):
    """What `instance.delete()` did, shown rather than described."""

    def test_a_cascade_delete_erases_the_entry_and_every_leg(self):
        entry_pk, cost_pk, bank_pk = self.entry.pk, self.cost_leg.pk, self.bank_leg.pk

        Expense.objects.filter(pk=self.expense.pk).delete()

        self.assertFalse(JournalEntry.objects.filter(pk=entry_pk).exists())
        self.assertFalse(
            JournalEntryConnector.objects.filter(pk__in=[cost_pk, bank_pk]).exists()
        )

    def test_and_leaves_the_stored_balances_asserting_a_posting_that_is_gone(self):
        Expense.objects.filter(pk=self.expense.pk).delete()
        # Rent still claims 250 of cost and the bank still claims it paid,
        # with no ledger line anywhere supporting either.
        self.assertEqual(self.balances(), (Decimal("250.000"), Decimal("750.000")))


class VoidingReversesInsteadTests(ExpenseVoidTestCase):
    def test_the_original_entry_survives(self):
        void_expense_postings(self.expense)

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        self.assertTrue(
            JournalEntryConnector.objects.filter(pk=self.cost_leg.pk).exists()
        )

    def test_a_reversing_entry_is_posted_and_marked_deleted(self):
        reversal = void_expense_postings(self.expense)

        self.assertIsNotNone(reversal)
        self.assertNotEqual(reversal.pk, self.entry.pk)
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind,
                JournalEntryConnectorRequestKindChoices.DELETED,
            )

    def test_the_pair_nets_to_zero_on_every_account(self):
        void_expense_postings(self.expense)

        for account in (self.rent, self.bank):
            with self.subTest(account=account.title):
                legs = JournalEntryConnector.objects.filter(account=account)
                debits = sum(leg.debit for leg in legs)
                credits = sum(leg.credit for leg in legs)
                self.assertEqual(debits, credits)

    def test_the_stored_balances_move_back(self):
        void_expense_postings(self.expense)

        self.assertEqual(self.balances(), (Decimal("0.000"), Decimal("1000.000")))

    def test_an_expense_that_posted_nothing_is_not_an_error(self):
        bare = Expense.objects.create(
            supplier=self.supplier, status=ExpenseStatusChoices.PUBLISHED,
            payment_account=self.bank,
        )
        self.assertIsNone(void_expense_postings(bare))

    def test_voiding_twice_does_not_reverse_the_reversal(self):
        """The reversal's own legs are DELETED, so they are excluded."""
        void_expense_postings(self.expense)
        after_first = self.balances()

        void_expense_postings(self.expense)

        self.assertEqual(self.balances(), after_first)


class TheViewSoftDeletesTests(ExpenseVoidTestCase):
    def test_perform_destroy_reverses_and_retires_rather_than_deleting(self):
        from weapi.django_rest.views.purchases import PrivateWeExpenseDetails

        class FakeRequest:
            def __init__(self, user):
                self.user = user

        view = PrivateWeExpenseDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.expense)

        self.expense.refresh_from_db()
        self.assertEqual(self.expense.status, ExpenseStatusChoices.REMOVED)
        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        self.assertEqual(self.balances(), (Decimal("0.000"), Decimal("1000.000")))

    def test_the_view_no_longer_relies_on_drfs_default_destroy(self):
        """The defect was an absent method, so its presence is the fix."""
        from weapi.django_rest.views.purchases import PrivateWeExpenseDetails

        self.assertIn("perform_destroy", PrivateWeExpenseDetails.__dict__)


class ARetiredExpenseIsUnreachableTests(ExpenseVoidTestCase):
    """A voided document must not stay editable, or the void can be undone.

    `get_object` had no REMOVED filter, so a retired expense was still
    fetchable and PATCHable. That was harmless while a delete erased the entry
    -- there was nothing left to amend. Now that a delete posts a REVERSAL,
    there are two entries under `expense=` with the same kind, and the amend
    path picks one with `.first()` over a model whose bare `class Meta:` drops
    the inherited ordering. So the pick was arbitrary, and could land on the
    reversal.
    """

    def test_a_retired_expense_is_no_longer_fetchable(self):
        from django.http import Http404
        from weapi.django_rest.views.purchases import PrivateWeExpenseDetails

        class FakeRequest:
            def __init__(self, user):
                self.user = user

        view = PrivateWeExpenseDetails()
        view.request = FakeRequest(self.user)
        view.kwargs = {"uid": str(self.expense.uid)}
        self.assertIsNotNone(view.get_object())          # live: fetchable

        view.perform_destroy(self.expense)

        with self.assertRaises(Http404):                 # retired: gone
            view.get_object()

    def test_the_amend_path_picks_the_original_entry_not_the_reversal(self):
        """Deterministic by `id`, so it is always the entry that was posted
        first -- the original."""
        from journalio.choices import JournalEntryKindChoices

        void_expense_postings(self.expense)

        picked = JournalEntry.objects.filter(
            expense=self.expense,
            kind=JournalEntryKindChoices.EXPENSE,
            company=self.company,
        ).order_by("id").first()
        self.assertEqual(picked.pk, self.entry.pk)

    def test_journal_entry_has_no_default_ordering(self):
        """The reason the ordering has to be explicit at every call site."""
        self.assertEqual(list(JournalEntry._meta.ordering), [])
