"""Retiring a supplier destroyed their entire ledger history.

The twin of the customer defect fixed in `c213f2b7` — the customer version was copied from
this one, comment and all ("When deleting a supplier, we need to update the balance…").

`PrivateWeSupplierDetails.perform_destroy` did three things beyond setting a status:

**It voided their whole history.** Every bill, payment and vendor credit the supplier had
ever appeared in, marked REMOVED in one bulk update. No reversing entry, so no audit trail,
and nothing sets an entry's status back — not reversible through the API. Cost and tax
recognised in closed periods silently vanished from every report.

**It moved two account balances with no journal entry** — root cause R2. One was "Other
Miscellaneous Expense", which has nothing to do with a supplier's payable.

**Neither account was guarded.** `get_chart_of_account` returns a dict, so a company lacking
either name yielded `None`, and `update_opening_balance(None, …)` raised — a 500 on
retiring a supplier.

Retiring a supplier is a master-data change with no accounting consequence: their bills
remain valid, their balance remains in A/P, and the ageing report still shows them.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from supplierio.choices import SupplierStatusChoices
from supplierio.models import Supplier


class RetireSupplierTests(TestCase):
    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def supplier(self, name="Widgets"):
        return Supplier.objects.create(
            company=self.company, first_name=name, display_name=name,
            opening_balance=self.BASELINE,
        )

    def account(self, title, kind=ChartOfAccountKindChoices.LIABILITIES):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def posted_entry(self, supplier, account, amount=Decimal("250")):
        entry = JournalEntry.objects.create(
            company=self.company, entry_number=f"JE-{supplier.pk}-{account.pk}",
            amount=amount, status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.PURCHASE,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account, supplier=supplier,
            kind=JournalEntryConnectorKindChoices.CREDIT,
            debit=0, credit=amount, total=amount,
            last_balance=account.opening_balance,
        )
        return entry

    def retire(self, supplier):
        from weapi.django_rest.views.suppliers import PrivateWeSupplierDetails

        PrivateWeSupplierDetails().perform_destroy(supplier)

    def test_the_supplier_is_retired(self):
        supplier = self.supplier()

        self.retire(supplier)

        supplier.refresh_from_db()
        self.assertEqual(supplier.status, SupplierStatusChoices.REMOVED)

    def test_their_bills_survive(self):
        supplier = self.supplier()
        payable = self.account("Accounts Payable (A/P)")
        entry = self.posted_entry(supplier, payable)

        self.retire(supplier)

        entry.refresh_from_db()
        self.assertEqual(
            entry.status,
            JournalEntryStatusChoices.PUBLISHED,
            "retiring a supplier must not void their history",
        )

    def test_every_entry_survives_not_just_the_first(self):
        supplier = self.supplier()
        payable = self.account("Accounts Payable (A/P)")
        others = [
            self.account(f"Expense {i}", ChartOfAccountKindChoices.EXPENSES)
            for i in range(3)
        ]
        entries = [self.posted_entry(supplier, a) for a in [payable, *others]]

        self.retire(supplier)

        for entry in entries:
            entry.refresh_from_db()
            with self.subTest(entry=entry.pk):
                self.assertEqual(entry.status, JournalEntryStatusChoices.PUBLISHED)

    def test_no_account_balance_moves(self):
        supplier = self.supplier()
        payable = self.account("Accounts Payable (A/P)")
        misc = self.account(
            "Other Miscellaneous Expense", ChartOfAccountKindChoices.EXPENSES
        )

        self.retire(supplier)

        for account in (payable, misc):
            account.refresh_from_db()
            with self.subTest(account=account.title):
                self.assertEqual(
                    Decimal(str(account.opening_balance)), self.BASELINE
                )

    def test_the_supplier_balance_is_left_alone(self):
        supplier = self.supplier()

        self.retire(supplier)

        supplier.refresh_from_db()
        self.assertEqual(Decimal(str(supplier.opening_balance)), self.BASELINE)

    def test_it_works_in_a_company_with_no_ap_account(self):
        """It used to 500 -- `.get()` on the dict yields None."""
        supplier = self.supplier()
        self.assertFalse(
            ChartOfAccount.objects.filter(
                company=self.company, title="Accounts Payable (A/P)"
            ).exists()
        )

        self.retire(supplier)

        supplier.refresh_from_db()
        self.assertEqual(supplier.status, SupplierStatusChoices.REMOVED)


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.views import suppliers

        return inspect.getsource(suppliers)

    def test_no_bulk_journal_status_update_remains(self):
        self.assertNotIn(
            "JournalEntry.objects.filter(journalentryconnector__supplier=instance).update(",
            self.source(),
        )

    def test_retiring_is_a_status_change_and_nothing_else(self):
        source = self.source()
        body = source.split("def perform_destroy(self, instance):")[1]
        body = body.split('"""')[2].split("class ")[0]

        self.assertIn("instance.status = SupplierStatusChoices.REMOVED", body)
        self.assertNotIn("JournalEntry", body)
        self.assertNotIn("update_opening_balance", body)

    def test_the_customer_twin_stays_fixed(self):
        """Both halves of the same defect; neither may regress alone."""
        import inspect

        from weapi.django_rest.views import customers

        self.assertNotIn(
            "JournalEntry.objects.filter(journalentryconnector__customer=instance).update(",
            inspect.getsource(customers),
        )
