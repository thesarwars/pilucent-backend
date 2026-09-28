"""Deleting a posted payroll run must not orphan its journal entries.

`JournalEntry.payroll_salary` is `SET_NULL`, so a hard delete of the run leaves
the entries behind -- still balanced into the accounts, with nothing left to say
what created them.

Production carries two such orphans: journals 2697 and 2698, byte-identical to
each other, `payroll_salary` NULL on both, each moving 140,966.12 of wages and
taxes that no payroll run claims. They are also each out of balance by 240.84,
so they cannot even be reconstructed from what they contain.

`PayrollSalaryProcessDetailView` was a bare `RetrieveDestroyAPIView` with no
`perform_destroy` and no status check. Voiding -- which reverses the entries
through `reverse_payroll_entries` inside a transaction -- is the supported way
to undo a posted run, and it already existed one class below.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.serializers import ValidationError

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
)
from accounts.models import ChartOfAccount, User

from common.django_rest.helpers.balance_helpers import update_opening_balance

from companyio.models import Company

from employeeio.models import Employee

from journalio.choices import JournalEntryKindChoices
from journalio.choices import JournalEntryConnectorKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

from payrollio.choicess import PayrollSalaryProcessStatusChoices
from payrollio.models import PayrollSalaryProcess

from weapi.django_rest.views.payroll.salary_process import (
    PayrollSalaryProcessDetailView,
)


class PayrollDeleteGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Balanzify LTD")
        cls.user = User.objects.create_user(
            name="Michael olyse", email="payroll-delete@example.com",
            password="pass1234!",
        )
        cls.employee = Employee.objects.create(user=cls.user, name="Michael olyse")
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def run_process(self):
        return PayrollSalaryProcess.objects.create(
            employee=self.employee,
            title="monthly salary process",
            pay_date=date(2026, 7, 21),
            payment_account=self.bank,
        )

    def destroy(self, instance):
        PayrollSalaryProcessDetailView().perform_destroy(instance)

    def test_a_finalized_run_cannot_be_deleted(self):
        run = self.run_process()
        run.status = PayrollSalaryProcessStatusChoices.FINALIZED
        run.save(update_fields=["status"])
        JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            payroll_salary=run,
        )

        with self.assertRaises(ValidationError) as raised:
            self.destroy(run)

        self.assertIn("Void it", str(raised.exception))
        self.assertTrue(
            PayrollSalaryProcess.objects.filter(pk=run.pk).exists(),
            "the run was deleted despite having posted",
        )

    def test_the_journal_entry_survives_the_refusal(self):
        run = self.run_process()
        run.status = PayrollSalaryProcessStatusChoices.FINALIZED
        run.save(update_fields=["status"])
        entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            payroll_salary=run,
        )

        with self.assertRaises(ValidationError):
            self.destroy(run)

        entry.refresh_from_db()
        self.assertEqual(entry.payroll_salary_id, run.pk)

    def test_a_draft_deletes_and_unwinds_what_it_posted(self):
        """The dead-end this must not recreate.

        A DRAFT run HAS posted -- post_payroll_entries writes an entry on
        create -- and `void_payroll` raises unless the run is FINALIZED. A
        blanket refusal here left a draft neither deletable nor voidable.
        """
        run = self.run_process()
        account = ChartOfAccount.objects.create(
            company=self.company, title="Wages", code="6000",
            kind=ChartOfAccountKindChoices.EXPENSES,
            opening_balance=Decimal("1000"),
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            payroll_salary=run,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("250.32"), credit=0,
        )
        update_opening_balance(account, "credit", Decimal("250.32"), 0)
        account.refresh_from_db()

        self.destroy(run)

        self.assertFalse(PayrollSalaryProcess.objects.filter(pk=run.pk).exists())
        self.assertFalse(JournalEntry.objects.filter(pk=entry.pk).exists())
        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), Decimal("1000"))

    def test_the_orphaning_this_prevents(self):
        """Shows what the old behaviour produced, via the FK's own rule.

        Deleting the run directly -- as the unguarded view did -- leaves the
        entry in place with a NULL link. That is journals 2697 and 2698.
        """
        run = self.run_process()
        entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            payroll_salary=run,
        )

        PayrollSalaryProcess.objects.filter(pk=run.pk).delete()

        entry.refresh_from_db()
        self.assertIsNone(entry.payroll_salary_id)
