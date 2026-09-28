"""The admin delete that 500s today, and what the purge command must not take with it.

Deleting a user in the admin dies at COMMIT with

    violates foreign key constraint "payrollio_payrollsal_employee_id_35b6c426_fk_employeei"

because `PayrollSalaryProcess.employee` is `DO_NOTHING` while the database still
enforces the constraint. `purge_users` walks the graph with those edges made
traversable for the length of one run.

The risk in doing that is over-reach, so most of what is asserted here is what
the command leaves alone: the shared company, bystanding users, the ledger FKs,
and the `on_delete` values themselves once the run is over.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.deletion import DO_NOTHING
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.management.commands.purge_users import (
    LEDGER_GUARDED,
    do_nothing_as_cascade,
)
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from employeeio.models import Employee

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from payrollio.models import PayrollSalaryProcess


class PurgeUsersTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Balanzify LTD")
        self.bank = ChartOfAccount.objects.create(
            company=self.company,
            title="City Bank",
            code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.doomed = self.make_user("doomed@example.com")
        self.bystander = self.make_user("bystander@example.com")

    def make_user(self, email):
        user = User.objects.create_user(
            name=email.split("@")[0], email=email, password="pass1234!"
        )
        CompanyUser.objects.create(user=user, company=self.company)
        employee = Employee.objects.create(user=user, name=user.name)
        PayrollSalaryProcess.objects.create(
            employee=employee,
            title="monthly salary process",
            pay_date=date(2026, 7, 21),
            payment_account=self.bank,
        )
        return user

    def purge(self, *args):
        out = StringIO()
        call_command("purge_users", *args, stdout=out, stderr=out)
        return out.getvalue()

    # -- the reported bug ---------------------------------------------------

    def test_a_user_with_payroll_history_deletes(self):
        """This is the exact shape that raises IntegrityError in the admin."""
        employee_id = self.doomed.employee_set.get().id

        self.purge("doomed@example.com", "--apply")

        self.assertFalse(User.objects.filter(email="doomed@example.com").exists())
        self.assertFalse(Employee.objects.filter(id=employee_id).exists())
        self.assertFalse(
            PayrollSalaryProcess.objects.filter(employee_id=employee_id).exists(),
            "the payroll run that blocks the admin delete was left behind",
        )

    def test_the_plain_orm_delete_still_fails(self):
        """Guards the premise: without the command, this is still broken.

        If Django ever starts collecting `DO_NOTHING` rows on its own, or the FK
        gets migrated, this test fails and the command has become unnecessary.
        """
        self.assertIs(
            PayrollSalaryProcess._meta.get_field("employee").remote_field.on_delete,
            DO_NOTHING,
        )

    # -- what it must not touch ---------------------------------------------

    def test_the_company_survives(self):
        self.purge("doomed@example.com", "--apply")
        self.assertTrue(Company.objects.filter(id=self.company.id).exists())

    def test_bystanders_survive(self):
        bystander_employee = self.bystander.employee_set.get().id

        self.purge("doomed@example.com", "--apply")

        self.assertTrue(User.objects.filter(id=self.bystander.id).exists())
        self.assertTrue(Employee.objects.filter(id=bystander_employee).exists())
        self.assertTrue(
            PayrollSalaryProcess.objects.filter(
                employee_id=bystander_employee
            ).exists()
        )

    def test_dry_run_writes_nothing(self):
        output = self.purge("doomed@example.com")

        self.assertIn("Dry run", output)
        self.assertTrue(User.objects.filter(email="doomed@example.com").exists())
        self.assertEqual(PayrollSalaryProcess.objects.count(), 2)

    def test_dry_run_reports_the_same_rows_it_would_delete(self):
        output = self.purge("doomed@example.com")
        self.assertIn("payrollio.PayrollSalaryProcess", output)
        self.assertIn("employeeio.Employee", output)

    # -- the override is temporary and scoped -------------------------------

    def test_on_delete_is_restored_after_a_run(self):
        self.purge("doomed@example.com", "--apply")
        self.assertIs(
            PayrollSalaryProcess._meta.get_field("employee").remote_field.on_delete,
            DO_NOTHING,
            "the registry was left rewritten for the rest of the process",
        )

    def test_on_delete_is_restored_even_when_the_run_raises(self):
        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            with do_nothing_as_cascade():
                raise Boom()

        self.assertIs(
            PayrollSalaryProcess._meta.get_field("employee").remote_field.on_delete,
            DO_NOTHING,
        )

    def test_ledger_foreign_keys_are_never_flipped(self):
        """`JournalEntryConnector` is the ledger. Nothing may cascade into it.

        Its `account` FK is PROTECT for exactly this reason, but `warehose` and
        `tax` on the same row are DO_NOTHING -- flipping those would delete
        journal legs while the parent entry, which has no FK to either, survived
        holding the rest. Permanently unbalanced books, no record of why.
        """
        with do_nothing_as_cascade() as (patched, skipped):
            for label, field_name in LEDGER_GUARDED:
                field = JournalEntryConnector._meta.get_field(field_name)
                self.assertIs(
                    field.remote_field.on_delete,
                    DO_NOTHING,
                    f"{label}.{field_name} was made cascadable",
                )
            self.assertEqual(len(skipped), len(LEDGER_GUARDED))
            self.assertNotIn(
                JournalEntryConnector._meta.get_field("warehose"), patched
            )

    def test_protect_is_left_alone(self):
        with do_nothing_as_cascade():
            self.assertEqual(
                JournalEntryConnector._meta.get_field("account").remote_field.on_delete.__name__,
                "PROTECT",
            )

    # -- identifier handling ------------------------------------------------

    def test_identifiers_resolve_by_email_uid_and_id(self):
        for identifier in (
            self.doomed.email,
            str(self.doomed.uid),
            str(self.doomed.id),
        ):
            with self.subTest(identifier=identifier):
                output = self.purge(identifier)
                self.assertIn("Users targeted: 1", output)
                self.assertIn(self.doomed.email, output)

    def test_a_file_of_identifiers_is_accepted(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("# junk accounts\n\ndoomed@example.com\n")
            path = handle.name

        output = self.purge("--file", path)
        self.assertIn("Users targeted: 1", output)

    def test_unmatched_identifiers_are_reported_not_swallowed(self):
        output = self.purge("doomed@example.com", "nobody@example.com")
        self.assertIn("matched no user", output)
        self.assertIn("nobody@example.com", output)

    def test_no_match_at_all_is_an_error(self):
        with self.assertRaises(CommandError):
            self.purge("nobody@example.com")

    def test_garbage_identifier_is_an_error(self):
        with self.assertRaises(CommandError):
            self.purge("not-an-email-or-uid")

    def test_no_identifiers_is_an_error(self):
        with self.assertRaises(CommandError):
            self.purge()

    # -- orphan company reporting -------------------------------------------

    def test_a_company_left_memberless_is_reported_but_kept(self):
        solo = Company.objects.create(name="Solo Test Co")
        CompanyUser.objects.create(user=self.doomed, company=solo)

        output = self.purge("doomed@example.com", "--apply")

        self.assertIn("Solo Test Co", output)
        self.assertIn("zero members", output)
        self.assertTrue(Company.objects.filter(id=solo.id).exists())

    def test_a_company_holding_a_ledger_refuses_to_be_purged(self):
        """The PROTECT guard fires from inside the cascade, exactly as intended.

        `JournalEntryConnector.account` is PROTECT so that deleting an account
        cannot erase journal legs. It raises even when the protecting rows are
        part of the same cascade, which is what stops `--with-orphan-companies`
        from taking a real set of books with it.
        """
        solo = Company.objects.create(name="Solo Books Co")
        CompanyUser.objects.create(user=self.doomed, company=solo)
        account = ChartOfAccount.objects.create(
            company=solo,
            title="Wages",
            code="6000",
            kind=ChartOfAccountKindChoices.EXPENSES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        entry = JournalEntry.objects.create(
            company=solo, kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS
        )
        JournalEntryConnector.objects.create(
            journal=entry,
            account=account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("250.32"),
            credit=0,
        )

        with self.assertRaises(CommandError) as raised:
            self.purge("doomed@example.com", "--with-orphan-companies", "--apply")

        self.assertIn("PROTECT", str(raised.exception))
        self.assertTrue(Company.objects.filter(id=solo.id).exists())
        self.assertTrue(
            User.objects.filter(id=self.doomed.id).exists(),
            "the refusal must roll back the user delete too, not half-apply it",
        )

    def test_with_orphan_companies_deletes_it(self):
        solo = Company.objects.create(name="Solo Test Co")
        CompanyUser.objects.create(user=self.doomed, company=solo)

        self.purge("doomed@example.com", "--with-orphan-companies", "--apply")

        self.assertFalse(Company.objects.filter(id=solo.id).exists())
        self.assertTrue(
            Company.objects.filter(id=self.company.id).exists(),
            "the shared company was deleted along with the solo one",
        )
