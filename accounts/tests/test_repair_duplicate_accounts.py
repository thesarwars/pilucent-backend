"""COA #16 — retiring duplicate titles so the unique index can be added.

`AddConstraint` validates against live data, so one duplicate fails the migration for
everyone. `audit_duplicate_accounts` reports the blocking groups; this repairs them.

Two properties matter more than the mechanics:

**Nothing is ever hard-deleted.** Rows are retired with `status = REMOVED`, so every one
stays recoverable and `JournalEntryConnector.account` (PROTECT) is never challenged.

**A group where more than one row carries journal lines is left alone.** Choosing which of
two transacted accounts survives is a bookkeeping decision about where history belongs. A
rule that guesses would silently move somebody's ledger, so it reports and stops.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from common.test_support import PreConstraintDataMixin

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector


class RepairDuplicateAccountsTests(PreConstraintDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, *, code="", system_key=None, is_fixed=False):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=code,
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            system_key=system_key, is_fixed=is_fixed,
        )

    def give_history(self, account):
        entry = JournalEntry.objects.create(
            company=self.company, entry_number=f"JE-{account.pk}", amount=10,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=10, credit=0, total=10, last_balance=0,
        )

    def run_cmd(self, *flags):
        out = StringIO()
        call_command(
            "repair_duplicate_accounts",
            f"--company={self.company.pk}",
            *flags,
            stdout=out,
            stderr=StringIO(),
        )
        return out.getvalue()

    def live(self):
        return ChartOfAccount.objects.filter(
            company=self.company
        ).exclude(status=ChartOfAccountStatusChoices.REMOVED)

    # --- the safety properties ------------------------------------------

    def test_dry_run_writes_nothing(self):
        self.account("Prepaid Insurance")
        self.account("Prepaid Insurance")

        output = self.run_cmd()

        self.assertIn("DRY RUN", output)
        self.assertEqual(self.live().count(), 2)

    def test_nothing_is_ever_hard_deleted(self):
        a = self.account("Prepaid Insurance")
        b = self.account("Prepaid Insurance")

        self.run_cmd("--apply")

        self.assertTrue(ChartOfAccount.objects.filter(pk=a.pk).exists())
        self.assertTrue(ChartOfAccount.objects.filter(pk=b.pk).exists())
        self.assertEqual(self.live().count(), 1)

    def test_a_group_with_two_transacted_rows_is_left_alone(self):
        """The bookkeeping decision a rule must not make."""
        a = self.account("Prepaid Insurance")
        b = self.account("Prepaid Insurance")
        self.give_history(a)
        self.give_history(b)

        output = self.run_cmd("--apply")

        self.assertIn("LEFT ALONE", output)
        self.assertEqual(self.live().count(), 2, "neither may be retired")

    # --- which row survives ---------------------------------------------

    def test_the_row_with_history_survives(self):
        plain = self.account("Prepaid Insurance")
        transacted = self.account("Prepaid Insurance")
        self.give_history(transacted)

        self.run_cmd("--apply")

        transacted.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual(transacted.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertEqual(plain.status, ChartOfAccountStatusChoices.REMOVED)

    def test_the_system_key_row_survives_when_neither_has_history(self):
        plain = self.account("Sales Tax Payable")
        keyed = self.account("Sales Tax Payable", system_key="SALES_TAX_PAYABLE")

        self.run_cmd("--apply")

        keyed.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual(keyed.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertEqual(plain.status, ChartOfAccountStatusChoices.REMOVED)

    def test_history_outranks_the_system_key(self):
        keyed = self.account("Sales Tax Payable", system_key="SALES_TAX_PAYABLE")
        transacted = self.account("Sales Tax Payable")
        self.give_history(transacted)

        self.run_cmd("--apply")

        transacted.refresh_from_db()
        self.assertEqual(
            transacted.status,
            ChartOfAccountStatusChoices.ACTIVE,
            "history decides before any other rule",
        )

    def test_the_fixed_row_survives_over_a_plain_one(self):
        plain = self.account("Opening Balance Equity")
        fixed = self.account("Opening Balance Equity", is_fixed=True)

        self.run_cmd("--apply")

        fixed.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual(fixed.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertEqual(plain.status, ChartOfAccountStatusChoices.REMOVED)

    def test_otherwise_the_oldest_survives(self):
        first = self.account("Prepaid Insurance")
        second = self.account("Prepaid Insurance")

        self.run_cmd("--apply")

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertEqual(second.status, ChartOfAccountStatusChoices.REMOVED)

    # --- the shape it measures ------------------------------------------

    def test_it_groups_case_insensitively(self):
        """The index is on UPPER(title); the repair must match it."""
        self.account("Prepaid Insurance")
        self.account("PREPAID INSURANCE")

        self.run_cmd("--apply")

        self.assertEqual(self.live().count(), 1)

    def test_blank_titles_are_not_touched(self):
        """The index carves them out, so they are not duplicates."""
        self.account("")
        self.account("")

        self.run_cmd("--apply")

        self.assertEqual(self.live().count(), 2)

    def test_an_already_removed_row_does_not_count_as_a_duplicate(self):
        keep = self.account("Prepaid Insurance")
        gone = self.account("Prepaid Insurance")
        gone.status = ChartOfAccountStatusChoices.REMOVED
        gone.save()

        output = self.run_cmd("--apply")

        keep.refresh_from_db()
        self.assertEqual(keep.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertIn("Nothing to do", output)

    def test_a_clean_company_is_a_no_op(self):
        self.account("Office Supplies")
        self.account("Rent")

        output = self.run_cmd("--apply")

        self.assertIn("Nothing to do", output)
        self.assertEqual(self.live().count(), 2)

    def test_it_reports_why_each_survivor_was_chosen(self):
        self.account("Prepaid Insurance")
        self.account("Prepaid Insurance")

        output = self.run_cmd()

        self.assertIn("survivor chosen by", output)

    def test_another_company_is_untouched(self):
        other = Company.objects.create(name="Other Co")
        a = ChartOfAccount.objects.create(
            company=other, title="Prepaid Insurance",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        b = ChartOfAccount.objects.create(
            company=other, title="Prepaid Insurance",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

        self.account("Prepaid Insurance")
        self.account("Prepaid Insurance")
        self.run_cmd("--apply")

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertEqual(b.status, ChartOfAccountStatusChoices.ACTIVE)


class ConstraintEnforcedTests(TestCase):
    """COA #16 itself. Deliberately does NOT drop the index.

    If this class ever runs after one that drops the index without restoring it,
    these fail -- which is the point: the restore in `PreConstraintDataMixin` is
    load-bearing, and a silent failure to restore would weaken every test that
    relies on the constraint.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Constrained Co")

    def account(self, title, **kw):
        return ChartOfAccount.objects.create(
            company=self.company, title=title,
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, **kw
        )

    def test_two_live_accounts_cannot_share_a_title(self):
        from django.db import IntegrityError

        self.account("Prepaid Insurance")
        with self.assertRaises(IntegrityError):
            self.account("Prepaid Insurance")

    def test_case_differing_titles_collide_too(self):
        """UPPER(title) -- the case the index exists for."""
        from django.db import IntegrityError

        self.account("Health Insurance")
        with self.assertRaises(IntegrityError):
            self.account("health insurance")

    def test_a_removed_row_does_not_block_its_replacement(self):
        """Deletion is soft here, so without the carve-out a company could never
        recover from retiring an account."""
        first = self.account("Office Supplies")
        first.status = ChartOfAccountStatusChoices.REMOVED
        first.save()

        replacement = self.account("Office Supplies")

        self.assertEqual(replacement.status, ChartOfAccountStatusChoices.ACTIVE)

    def test_blank_titles_do_not_collide_with_each_other(self):
        """`title` is non-null with no default, so omitted kwargs persist as ''."""
        self.account("")
        self.account("")

        self.assertEqual(
            ChartOfAccount.objects.filter(company=self.company, title="").count(), 2
        )

    def test_two_companies_may_both_use_a_title(self):
        other = Company.objects.create(name="Other Co")

        self.account("Prepaid Insurance")
        ChartOfAccount.objects.create(
            company=other, title="Prepaid Insurance",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

        self.assertEqual(
            ChartOfAccount.objects.filter(title="Prepaid Insurance").count(), 2
        )

    def test_there_is_no_companion_constraint_on_code(self):
        """Deliberately absent -- `code` has no consumer and blanks self-collide."""
        names = {c.name for c in ChartOfAccount._meta.constraints}

        self.assertIn("unique_title_per_company_ci", names)
        self.assertNotIn("unique_code_per_company", names)
