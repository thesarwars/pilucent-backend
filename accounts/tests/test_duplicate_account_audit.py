"""The duplicate-account pre-flight has to measure the constraint it precedes.

`audit_duplicate_accounts` exists to answer one question: is production clean
enough to add the partial unique index? `AddConstraint` validates against live
data, so one missed duplicate fails the migration on deploy.

It grouped on the raw `title`, case-sensitively, and counted blank titles. The
recommended index is on `UPPER(title)` carving out REMOVED **and** blanks. Both
differences mattered, and one of them silently:

    "Health Insurance" beside "health insurance"
        -> reported CLEAN, and AddConstraint would still have failed

That is the exact pair the gap report cites as the REASON for the index, via
payroll's `title__iexact` lookup. The audit was blind to its own motivating case.

    title = ""  (a non-null CharField with no default, so omitted kwargs persist
                 as '' rather than NULL)
        -> reported as a blocker the index would not block, inflating the cleanup

An audit that does not measure what the constraint enforces cannot tell you when
it is safe to add it -- in either direction.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from common.test_support import PreConstraintDataMixin


class DuplicateAuditTests(PreConstraintDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, *, code="", status=None):
        return ChartOfAccount.objects.create(
            company=self.company,
            title=title,
            code=code,
            kind=ChartOfAccountKindChoices.EXPENSES,
            status=status or ChartOfAccountStatusChoices.ACTIVE,
        )

    def run_audit(self, kind="title"):
        out = StringIO()
        call_command(
            "audit_duplicate_accounts",
            f"--company={self.company.pk}",
            f"--kind={kind}",
            stdout=out,
            stderr=StringIO(),
        )
        return out.getvalue()

    def test_case_differing_titles_are_reported(self):
        """The motivating case, and the one the old version called clean."""
        self.account("Health Insurance")
        self.account("health insurance")

        output = self.run_audit()

        self.assertIn("duplicate title : 1 group(s)", output.replace("title ", "title "))
        self.assertNotIn("Clean for the constraint", output)

    def test_both_rows_of_a_case_differing_pair_are_listed(self):
        """Listing must use the same key as grouping, or it prints one row."""
        self.account("Health Insurance")
        self.account("health insurance")

        output = self.run_audit()

        self.assertIn("'Health Insurance'", output)
        self.assertIn("'health insurance'", output)

    def test_blank_titles_are_not_reported(self):
        """The index carves them out, so they are not blockers."""
        self.account("")
        self.account("")

        output = self.run_audit()

        self.assertIn("Clean for the constraint", output)

    def test_removed_rows_are_not_reported(self):
        self.account("Office Supplies")
        self.account(
            "Office Supplies", status=ChartOfAccountStatusChoices.REMOVED
        )

        output = self.run_audit()

        self.assertIn("Clean for the constraint", output)

    def test_exact_duplicates_are_still_reported(self):
        self.account("Office Supplies")
        self.account("Office Supplies")

        output = self.run_audit()

        self.assertNotIn("Clean for the constraint", output)
        self.assertIn("must be", output)

    def test_a_clean_company_names_the_constraint_it_verified(self):
        """"Clean" is meaningless unless it says clean FOR WHAT."""
        self.account("Office Supplies")
        self.account("Rent")

        output = self.run_audit()

        self.assertIn("UPPER(title)", output)
        self.assertIn("status <> 'REMOVED'", output)

    def test_it_records_that_the_code_half_is_not_recommended(self):
        self.account("Office Supplies")

        output = self.run_audit()

        self.assertIn("(company, code) half is NOT recommended", output)

    def test_the_code_check_still_works_when_asked_for(self):
        """Dropping the recommendation must not remove the measurement."""
        self.account("One", code="5001")
        self.account("Two", code="5001")

        output = self.run_audit(kind="code")

        self.assertIn("duplicate code", output)
        self.assertNotIn("Clean for the constraint", output)

    def test_blank_codes_self_collide_which_is_why_that_half_is_dropped(self):
        """`code` is non-null with no default, so omitted kwargs persist as ''."""
        self.account("One", code="")
        self.account("Two", code="")

        output = self.run_audit(kind="code")

        # Two code-less rows are a duplicate group under a (company, code) index.
        self.assertIn("duplicate code", output)
        self.assertNotIn("Clean for the constraint", output)
