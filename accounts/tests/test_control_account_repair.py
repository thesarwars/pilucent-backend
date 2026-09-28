"""`repair_control_account_types` against the fault production actually has.

The first production dry run reported 62 rows and printed 60 of them as
`'Income' -> 'Income'`, which reads as a no-op. It was not: the account type
already agreed and the whole change was a detail type the seeder never resolved,
because the templates asked for `Service` and the category tree carries
`Service/Fee Income`. These pin both halves of that.
"""

import csv
import os
import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountSystemKeyChoices
from accounts.models import ChartOfAccount

from categoryio.choicess import CategoryKindChoices
from categoryio.models import Category

from companyio.models import Company


def taxonomy(title, parent=None):
    return Category.objects.create(
        title=title, parent=parent, company=None, kind=CategoryKindChoices.CHART_OF_ACCOUNT
    )


class KindCheckDepthTests(TestCase):
    """`audit_account_integrity`'s kind check against a depth-2 account type.

    Production reported `Jumatechs Ltd.`'s `CAO -1` as having a kind that
    disagreed with its account type. It did not: the type was `Interest Paid`,
    which sits at `Expenses -> Other Expenses -> Interest Paid`, and the check
    stopped one level up at `Other Expenses`.
    """

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(name="Acme Books")
        expenses = taxonomy("Expenses")
        other = taxonomy("Other Expenses", parent=expenses)
        self.interest_paid = taxonomy("Interest Paid", parent=other)

    def audit(self):
        out = StringIO()
        call_command("audit_account_integrity", stdout=out, stderr=out)
        return out.getvalue()

    def make(self, title, kind):
        return ChartOfAccount.objects.create(
            title=title,
            code="6100",
            company=self.company,
            kind=kind,
            account_type=self.interest_paid,
        )

    def test_depth_two_account_type_resolves_to_its_root(self):
        self.make("CAO -1", ChartOfAccountKindChoices.EXPENSES)

        output = self.audit()

        self.assertNotIn("CAO -1", output)
        self.assertIn("No inconsistent accounts found.", output)

    def test_kind_that_is_not_one_of_the_five_is_still_reported(self):
        """The genuine fault the false positive was sitting next to.

        'OTHER EXPENSES' is not a ChartOfAccountKindChoices value at all, so an
        account carrying it appears on no statement.
        """
        self.make("CAO -6", "OTHER EXPENSES")

        output = self.audit()

        self.assertIn("CAO -6", output)

    def test_a_real_disagreement_across_roots_is_still_reported(self):
        assets = taxonomy("Assets")
        bank = taxonomy("Bank", parent=assets)
        account = self.make("Insurance - Business", ChartOfAccountKindChoices.EXPENSES)
        account.account_type = bank
        account.save(update_fields=["account_type"])

        output = self.audit()

        self.assertIn("Insurance - Business", output)


class ControlAccountRepairTests(TestCase):
    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.company = Company.objects.create(name="Acme Books")
        root = taxonomy("Incomes")
        self.income = taxonomy("Income", parent=root)
        self.service_fee = taxonomy("Service/Fee Income", parent=self.income)

    def make_service_account(self, **kwargs):
        return ChartOfAccount.objects.create(
            title="Service",
            code="4100",
            company=self.company,
            kind=ChartOfAccountKindChoices.INCOMES,
            system_key=ChartOfAccountSystemKeyChoices.SERVICE,
            account_type=self.income,
            **kwargs,
        )

    def run_command(self, *args):
        out = StringIO()
        call_command("repair_control_account_types", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_null_detail_type_is_filled_from_the_template(self):
        account = self.make_service_account(detail_type=None)

        self.run_command("--apply")

        account.refresh_from_db()
        self.assertEqual(account.detail_type, self.service_fee)
        # The half that was already right must not move.
        self.assertEqual(account.account_type, self.income)
        self.assertEqual(account.kind, ChartOfAccountKindChoices.INCOMES)

    def test_dry_run_names_both_halves_and_writes_nothing(self):
        account = self.make_service_account(detail_type=None)

        output = self.run_command()

        self.assertIn("Service/Fee Income", output)
        self.assertIn("detail type only", output)
        # The old output printed only the account type, which here is unchanged.
        self.assertNotIn("'Income' -> 'Income'", output)
        account.refresh_from_db()
        self.assertIsNone(account.detail_type)

    def test_account_already_correct_is_not_reported(self):
        self.make_service_account(detail_type=self.service_fee)

        output = self.run_command()

        self.assertIn("detail type only          : 0", output)

    def test_never_writes_a_tenant_owned_category(self):
        """The fix for the hole that blocked the production run.

        `Category.company` is nullable and tenant-writable, and the model
        inherits `ordering = ("-created_at",)`, so a plain
        `filter(title=..., parent=...).first()` returns the NEWEST match. A
        tenant that created its own "Service/Fee Income" under the shipped
        `Income` node would have had that private row written into every other
        company's control account.
        """
        intruder_company = Company.objects.create(name="Someone Else Ltd")
        intruder = Category.objects.create(
            title="Service/Fee Income",
            parent=self.income,
            company=intruder_company,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        )
        # Newest, and identical by title -- so it wins any unscoped lookup.
        self.assertGreater(intruder.created_at, self.service_fee.created_at)

        account = self.make_service_account(detail_type=None)
        self.run_command("--apply")

        account.refresh_from_db()
        self.assertEqual(account.detail_type_id, self.service_fee.id)
        self.assertIsNone(account.detail_type.company_id)

    def test_snapshot_records_the_pre_state_by_id(self):
        account = self.make_service_account(detail_type=None)
        path = os.path.join(self.tmpdir, "pre.csv")

        self.run_command("--snapshot", path, "--apply")

        with open(path, newline="") as handle:
            rows = {int(r["chart_of_account_id"]): r for r in csv.DictReader(handle)}
        # Captured BEFORE the write, so it still shows the null it replaced.
        self.assertEqual(rows[account.id]["detail_type_id"], "")
        self.assertEqual(rows[account.id]["account_type_id"], str(self.income.id))

        account.refresh_from_db()
        self.assertEqual(account.detail_type, self.service_fee)

    def test_apply_without_a_snapshot_says_so(self):
        self.make_service_account(detail_type=None)

        output = self.run_command("--apply")

        self.assertIn("No --snapshot given", output)

    def test_missing_detail_category_never_writes_null(self):
        """The guard that matters: no answer is not the same as a null answer.

        A template naming a detail type the tree does not carry is what caused
        these 61 nulls in the first place. Repairing that by writing another null
        would be the command reproducing the bug it exists to fix.
        """
        self.service_fee.delete()
        account = self.make_service_account(detail_type=None)

        output = self.run_command("--apply")

        account.refresh_from_db()
        self.assertIsNone(account.detail_type)
        self.assertEqual(account.account_type, self.income)
        self.assertIn("no template answer        : 1", output)
