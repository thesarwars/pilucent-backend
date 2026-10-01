"""Saving a payroll run twice must not post it twice.

`PayrollSalaryProcessSerializer.create` is an upsert -- pass a `uid` and it
edits the existing run -- and `create_journal_entry` is a `get_or_create` keyed
on `payroll_salary`. So a second save did not replace the entry; it found the
same one and appended another full set of legs.

The entry stayed balanced each pass, because both sides were appended together.
That is exactly why the write-time balance check in
`create_journal_entry_connector` never caught it: what doubled was the number of
legs and every account's stored balance, not the debit-credit totals.

`unwind_existing_payroll_posting` reverses first, the reverse-and-repost shape
R5 settled on for sales. It is shared with the delete path, which needs the same
unwind for the mirror reason -- `JournalEntry.payroll_salary` is SET_NULL, so
deleting a run leaves its entries behind with their balances still applied.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company

from employeeio.models import Employee

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from payrollio.models import PayrollSalaryProcess

from weapi.django_rest.helpers.salary_process_journal_entry import (
    _post_credit,
    _post_debit,
    unwind_existing_payroll_posting,
)


class UnwindBeforeRepostTests(TestCase):
    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Pilucent LTD")
        cls.user = User.objects.create_user(
            name="Michael olyse", email="repost@example.com", password="pass1234!"
        )
        cls.employee = Employee.objects.create(
            company=cls.company, user=cls.user,
            code="EMP-0001", name_en="Michael olyse",
        )
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def run_process(self):
        return PayrollSalaryProcess.objects.create(
            employee=self.employee, title="monthly salary process",
            pay_date=date(2026, 7, 21), payment_account=self.bank,
        )

    def post_once(self, run, account, amount=Decimal("250.32")):
        """One posting pass: move the balance and write the connector."""
        entry, _ = JournalEntry.objects.get_or_create(
            payroll_salary=run,
            defaults={
                "company": self.company,
                "kind": JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            },
        )
        rows = []
        _post_debit(rows, account, amount)
        account.refresh_from_db()
        JournalEntryConnector.objects.create(
            journal=entry, account=account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=amount, credit=0,
        )
        return entry

    def wages(self):
        return ChartOfAccount.objects.create(
            company=self.company, title="Wages", code="6000",
            kind=ChartOfAccountKindChoices.EXPENSES,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def test_a_second_post_without_unwinding_doubles(self):
        """The defect, demonstrated."""
        run, account = self.run_process(), self.wages()

        self.post_once(run, account)
        self.post_once(run, account)

        account.refresh_from_db()
        self.assertEqual(
            Decimal(str(account.opening_balance)),
            self.BASELINE + Decimal("500.64"),
            "two posts should double -- that is what the fix prevents",
        )
        self.assertEqual(JournalEntry.objects.filter(payroll_salary=run).count(), 1)
        self.assertEqual(
            JournalEntryConnector.objects.filter(account=account).count(), 2
        )

    def test_unwinding_first_leaves_one_posting(self):
        run, account = self.run_process(), self.wages()

        self.post_once(run, account)
        unwind_existing_payroll_posting(run)
        self.post_once(run, account)

        account.refresh_from_db()
        self.assertEqual(
            Decimal(str(account.opening_balance)),
            self.BASELINE + Decimal("250.32"),
        )
        self.assertEqual(
            JournalEntryConnector.objects.filter(account=account).count(), 1
        )

    def test_unwinding_returns_every_balance_to_baseline(self):
        run, account = self.run_process(), self.wages()
        self.post_once(run, account)

        removed = unwind_existing_payroll_posting(run)

        self.assertEqual(removed, 1)
        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)
        self.assertEqual(JournalEntry.objects.filter(payroll_salary=run).count(), 0)

    def test_unwinding_a_run_that_never_posted_is_a_no_op(self):
        run = self.run_process()

        self.assertEqual(unwind_existing_payroll_posting(run), 0)

    def test_a_credit_leg_unwinds_too(self):
        run = self.run_process()
        account = self.wages()
        entry, _ = JournalEntry.objects.get_or_create(
            payroll_salary=run,
            defaults={
                "company": self.company,
                "kind": JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            },
        )
        rows = []
        _post_credit(rows, account, Decimal("250.32"))
        JournalEntryConnector.objects.create(
            journal=entry, account=account,
            kind=JournalEntryConnectorKindChoices.CREDIT,
            debit=0, credit=Decimal("250.32"),
        )

        unwind_existing_payroll_posting(run)

        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)


class RepostWiringTests(TestCase):
    """The serializer must unwind before it posts.

    Driving `create` needs an employee, a payment account, components and a
    company context. What regressed is the ORDER of two calls, so that is what
    this pins.
    """

    def source(self):
        import inspect

        from weapi.django_rest.serializers.payroll import salary_process

        return inspect.getsource(
            salary_process.PayrollSalaryProcessSerializer.create
        )

    def test_the_unwind_runs_before_the_post(self):
        source = self.source()

        unwind_at = source.index("unwind_existing_payroll_posting(payroll_instance)")
        post_at = source.index("post_payroll_entries(")
        self.assertLess(unwind_at, post_at)

    def test_the_delete_path_shares_the_same_unwind(self):
        """It was duplicated; duplication is why several of these existed twice."""
        import inspect

        from weapi.django_rest.views.payroll import salary_process as view_module

        source = inspect.getsource(
            view_module.PayrollSalaryProcessDetailView.perform_destroy
        )
        self.assertIn("unwind_existing_payroll_posting(instance)", source)
