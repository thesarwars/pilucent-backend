"""U1 — retiring a customer destroyed their entire ledger history.

`PrivateWeCustomerDetails.perform_destroy` did three things beyond setting a status, and
each was a separate fault.

**It voided their whole history.**

    JournalEntry.objects.filter(journalentryconnector__customer=instance).update(
        status=JournalEntryStatusChoices.REMOVED
    )

Every invoice, payment, credit note and refund the customer had ever appeared in, marked
removed in one bulk update. No reversing entry, so no audit trail of what happened or why,
and nothing sets an entry's status back, so it was **not reversible through the API**.
Revenue, tax and cost recognised in closed periods silently vanished from every report.
The customer row itself was only soft-deleted — so the record survived while its accounting
history did not, which is exactly the wrong way round.

**It moved two account balances with no journal entry** — root cause R2. One of the two was
`"Service"`, an income account with no relationship to a customer's receivable. The comment
above it read *"When deleting a supplier"*, because it was copied from the supplier path.

**Neither account was guarded.** `get_chart_of_account` returns a dict, so a company lacking
either name yielded `None`, and `update_opening_balance(None, …)` raised — a 500 on retiring
a customer.

The standard (`CUSTOMER_INDUSTRY_STANDARD.md` §4) is unambiguous: a customer with
transactions is never deleted, and making one inactive **must not touch the ledger at all**.
Their invoices remain valid, their balance remains in A/R, and the ageing report still shows
them.

Not fixed here, and identical: `views/suppliers.py:86-125` does the same three things to a
supplier. That is the supplier module's work.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from customerio.choices import CustomerStatusChoices
from customerio.models import Customer

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector


class RetireCustomerTests(TestCase):
    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def customer(self, name="Ada"):
        return Customer.objects.create(
            company=self.company, first_name=name, display_name=name,
            opening_balance=self.BASELINE,
        )

    def account(self, title, kind=ChartOfAccountKindChoices.ASSETS):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def posted_entry(self, customer, account, amount=Decimal("250")):
        entry = JournalEntry.objects.create(
            company=self.company, entry_number="JE-1", amount=amount,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account, customer=customer,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=amount, credit=0, total=amount,
            last_balance=account.opening_balance,
        )
        return entry

    def retire(self, customer):
        from weapi.django_rest.views.customers import PrivateWeCustomerDetails

        PrivateWeCustomerDetails().perform_destroy(customer)

    def test_the_customer_is_retired(self):
        customer = self.customer()

        self.retire(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, CustomerStatusChoices.REMOVED)

    def test_their_journal_entries_survive(self):
        """The defect: every entry they appeared in was marked REMOVED."""
        customer = self.customer()
        receivable = self.account("Accounts Receivable (A/R)")
        entry = self.posted_entry(customer, receivable)

        self.retire(customer)

        entry.refresh_from_db()
        self.assertEqual(
            entry.status,
            JournalEntryStatusChoices.PUBLISHED,
            "retiring a customer must not void their history",
        )

    def test_every_entry_survives_not_just_the_first(self):
        customer = self.customer()
        receivable = self.account("Accounts Receivable (A/R)")
        entries = [self.posted_entry(customer, receivable) for _ in range(3)]

        self.retire(customer)

        for entry in entries:
            entry.refresh_from_db()
            with self.subTest(entry=entry.pk):
                self.assertEqual(entry.status, JournalEntryStatusChoices.PUBLISHED)

    def test_no_account_balance_moves(self):
        """Two balances moved with no journal entry -- root cause R2."""
        customer = self.customer()
        receivable = self.account("Accounts Receivable (A/R)")
        service = self.account("Service", ChartOfAccountKindChoices.INCOMES)

        self.retire(customer)

        for account in (receivable, service):
            account.refresh_from_db()
            with self.subTest(account=account.title):
                self.assertEqual(
                    Decimal(str(account.opening_balance)), self.BASELINE
                )

    def test_the_customer_balance_is_left_alone(self):
        """Their balance stays in A/R -- the standard says so explicitly."""
        customer = self.customer()

        self.retire(customer)

        customer.refresh_from_db()
        self.assertEqual(
            Decimal(str(customer.opening_balance)), self.BASELINE
        )

    def test_it_works_in_a_company_with_no_ar_account(self):
        """It used to 500: get_chart_of_account returns a dict, .get() gives None."""
        customer = self.customer()
        self.assertFalse(
            ChartOfAccount.objects.filter(
                company=self.company, title="Accounts Receivable (A/R)"
            ).exists()
        )

        self.retire(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, CustomerStatusChoices.REMOVED)

    def test_a_customer_with_no_history_retires_too(self):
        customer = self.customer("Grace")

        self.retire(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, CustomerStatusChoices.REMOVED)


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.views import customers

        return inspect.getsource(customers)

    def test_no_bulk_journal_status_update_remains(self):
        source = self.source()

        self.assertNotIn(
            "JournalEntry.objects.filter(journalentryconnector__customer=instance).update(",
            source,
        )

    def test_no_balance_mutation_remains(self):
        source = self.source()
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("*")
        )

        self.assertNotIn("update_opening_balance(\n            receivable_account", code)
        self.assertNotIn("update_opening_balance(\n            chart_of_account", code)

    def test_the_copied_supplier_comment_is_gone(self):
        self.assertNotIn(
            "# When deleting a supplier, we need to update the balance", self.source()
        )

    def test_retiring_is_now_a_status_change_and_nothing_else(self):
        source = self.source()
        body = source.split("def perform_destroy(self, instance):")[1]
        body = body.split('"""')[2].split("class ")[0]

        self.assertIn("instance.status = CustomerStatusChoices.REMOVED", body)
        self.assertNotIn("JournalEntry", body)
        self.assertNotIn("update_opening_balance", body)


class SupplierTwinTests(TestCase):
    """The identical defect, one module over -- since fixed.

    This class was a tripwire: it asserted the supplier path *still* carried the
    bulk journal void, so the pair could not drift apart unnoticed while only one
    half was repaired. The supplier half landed with this commit, and the
    tripwire fired on cue, which is what it was for.

    It now guards the same pair from the other direction. The behavioural cover
    for the supplier path lives in `supplierio/tests_retire_supplier.py`; what is
    left here is only the cross-module assertion that neither half regresses
    alone, since it was the copy-paste between them that produced two of these
    in the first place.
    """

    def test_neither_path_voids_a_ledger_on_retire(self):
        import inspect

        from weapi.django_rest.views import customers, suppliers

        for module, relation in (
            (customers, "customer"),
            (suppliers, "supplier"),
        ):
            with self.subTest(module=module.__name__):
                self.assertNotIn(
                    f"JournalEntry.objects.filter(journalentryconnector__{relation}=instance).update(",
                    inspect.getsource(module),
                )
