"""What "orphaned" actually means once a user is deleted.

Deleting a user never deletes a company -- `Company` has no FK to `User`, only
the `CompanyUser` join. So the leftover is not a broken reference; it is a
tenant with intact books and nobody who can log in. This command finds those,
and must not confuse them with companies that still have a member.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import UserStatusChoices
from accounts.models import User

from companyio.choices import CompanyStatusChoices
from companyio.models import Company, CompanyUser

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry


class OrphanCompanyAuditTests(TestCase):
    def audit(self, *args):
        out = StringIO()
        call_command("audit_orphan_companies", *args, stdout=out, stderr=out)
        return out.getvalue()

    def make_user(self, email, status=UserStatusChoices.ACTIVE):
        return User.objects.create_user(
            name=email.split("@")[0],
            email=email,
            password="pass1234!",
            status=status,
        )

    def test_a_company_with_no_members_is_listed(self):
        Company.objects.create(name="Abandoned Co")
        self.assertIn("Abandoned Co", self.audit())

    def test_a_company_with_a_live_member_is_not_listed(self):
        company = Company.objects.create(name="Staffed Co")
        CompanyUser.objects.create(user=self.make_user("live@example.com"), company=company)

        self.assertNotIn("Staffed Co", self.audit())

    def test_a_company_whose_only_member_is_removed_is_listed(self):
        """A REMOVED user cannot log in, so the company is just as unreachable."""
        company = Company.objects.create(name="Ghost Co")
        CompanyUser.objects.create(
            user=self.make_user("gone@example.com", UserStatusChoices.REMOVED),
            company=company,
        )

        self.assertIn("Ghost Co", self.audit())

    def test_already_removed_companies_are_hidden_unless_asked_for(self):
        Company.objects.create(name="Retired Co", status=CompanyStatusChoices.REMOVED)

        self.assertNotIn("Retired Co", self.audit())
        self.assertIn("Retired Co", self.audit("--include-removed"))

    def test_a_company_holding_books_is_flagged(self):
        company = Company.objects.create(name="Has Books Co")
        JournalEntry.objects.create(
            company=company, kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS
        )

        output = self.audit()

        self.assertIn("Has Books Co", output)
        self.assertIn("hold journal entries", output)

    def test_min_journals_filters_out_the_empty_ones(self):
        Company.objects.create(name="Empty Co")
        with_books = Company.objects.create(name="Has Books Co")
        JournalEntry.objects.create(
            company=with_books, kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS
        )

        output = self.audit("--min-journals", "1")

        self.assertIn("Has Books Co", output)
        self.assertNotIn("Empty Co", output)

    def test_it_never_writes(self):
        company = Company.objects.create(name="Abandoned Co")

        self.audit()

        company.refresh_from_db()
        self.assertEqual(company.status, CompanyStatusChoices.ACTIVE)
        self.assertTrue(Company.objects.filter(id=company.id).exists())

    def test_a_clean_database_says_so(self):
        company = Company.objects.create(name="Staffed Co")
        CompanyUser.objects.create(user=self.make_user("live@example.com"), company=company)

        self.assertIn("No memberless companies found", self.audit())
