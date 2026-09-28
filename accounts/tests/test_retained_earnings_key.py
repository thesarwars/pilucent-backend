"""Retained Earnings was a control account in name only.

It is seeded by all twenty industry templates and lives on 55 of 60 production
companies, but it carried **no `system_key`** -- the only account in the spine
that did not. Everything that protects a control account keys off that
enumeration:

* `get_chart_of_account()` resolves by key, falling back to title;
* the serializer refuses to modify `is_fixed=True` rows;
* the DELETE view refuses to remove them.

So the one account every set of books eventually closes into was renameable,
retypeable and deletable, while A/R, A/P, Inventory Asset and Opening Balance
Equity beside it were not. Spec BLZ-FIN-COA-SPEC-001 s8 requires exactly one per
entity and forbids deleting, deactivating, merging or retyping it.

This is the protection half only. **Nothing posts to Retained Earnings yet** --
the virtual close of s5.1 does not exist (gap #30), so the account sits at zero
while income and expense accounts are never closed out. That is a separate and
much larger piece of work; this one makes sure the destination still exists and
is intact when it arrives.

P1.2a of `COA_FIX_PLAN_V3.md`, deliberately split from the virtual close so a
one-line safety fix does not wait behind a change that alters every prior-year
report.
"""

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices as Key,
)
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import (
    SYSTEM_KEY_TO_TITLE,
    TITLE_TO_SYSTEM_KEY,
    get_chart_of_account,
    missing_system_keys,
)

from companyio.choices import CompanyKindChoices
from companyio.models import Company


class RetainedEarningsIsAControlAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )

    def account(self):
        return ChartOfAccount.objects.get(
            company=self.company, system_key=Key.RETAINED_EARNINGS
        )

    def test_a_new_company_gets_one(self):
        account = self.account()

        self.assertEqual(account.title, "Retained Earnings")
        self.assertEqual(account.kind, ChartOfAccountKindChoices.EQUITIES)

    def test_it_is_protected(self):
        """The whole point: `is_fixed` is what the guards read."""
        self.assertTrue(self.account().is_fixed)

    def test_exactly_one_per_company(self):
        """Spec s8. Two would make the resolver's choice arbitrary."""
        self.assertEqual(
            ChartOfAccount.objects.filter(
                company=self.company, system_key=Key.RETAINED_EARNINGS
            ).count(),
            1,
        )

    def test_it_resolves_by_key_after_a_rename(self):
        """Why the key matters at all: the title is the user's to change."""
        account = self.account()
        account.title = "Accumulated Profits"
        account.save(update_fields=["title"])

        resolved = get_chart_of_account(["Retained Earnings"], self.company)

        self.assertEqual(resolved["Retained Earnings"].pk, account.pk)

    def test_the_key_and_the_title_map_agree(self):
        self.assertIn("Retained Earnings", TITLE_TO_SYSTEM_KEY)
        self.assertEqual(SYSTEM_KEY_TO_TITLE[Key.RETAINED_EARNINGS], "Retained Earnings")

    def test_a_company_that_has_one_is_not_reported_as_missing(self):
        self.assertNotIn(Key.RETAINED_EARNINGS, missing_system_keys(self.company))

    def test_a_company_without_one_is_reported(self):
        """The 6 production companies that have none must be findable."""
        self.account().delete()

        self.assertIn(Key.RETAINED_EARNINGS, missing_system_keys(self.company))

    def test_every_industry_template_ships_one(self):
        """`create_control_account` copies the row from the industry template.

        A template with no Retained Earnings row cannot heal a company that
        lacks the account, so the backfill would report it absent forever.
        """
        from companyio.django_rest.helpers.chart_of_accounts import chart_of_accounts

        for block in chart_of_accounts:
            titles = {row["title"] for row in block["chart_of_accounts"]}
            with self.subTest(industry=str(block["kind"])):
                self.assertIn("Retained Earnings", titles)


class BackfillProtectsWhatItKeysTests(TestCase):
    """Keyed but not `is_fixed` is half a control account.

    Production has four in exactly that state -- two Undeposited Funds, one A/P,
    one Service -- keyed by an earlier run of the backfill, before it also set
    the flag. The resolver already treats them as control accounts while the
    guards do not, which is the gap C2 closed everywhere else.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(
            name="Legacy Co", kind=CompanyKindChoices.ECOMMERCE
        )

    def test_it_keys_an_unkeyed_account_and_guards_it(self):
        ChartOfAccount.objects.filter(
            company=self.company, system_key=Key.RETAINED_EARNINGS
        ).update(system_key=None, is_fixed=False)

        call_command("backfill_system_keys", "--apply", verbosity=0)

        account = ChartOfAccount.objects.get(
            company=self.company, title="Retained Earnings"
        )
        self.assertEqual(account.system_key, Key.RETAINED_EARNINGS)
        self.assertTrue(account.is_fixed, "keyed but left editable")

    def test_it_guards_an_account_that_is_already_keyed(self):
        """The production case: the key is there, the flag is not."""
        ChartOfAccount.objects.filter(
            company=self.company, system_key=Key.UNDEPOSITED_FUNDS
        ).update(is_fixed=False)

        call_command("backfill_system_keys", "--apply", verbosity=0)

        self.assertTrue(
            ChartOfAccount.objects.get(
                company=self.company, system_key=Key.UNDEPOSITED_FUNDS
            ).is_fixed
        )

    def test_a_dry_run_changes_nothing(self):
        ChartOfAccount.objects.filter(
            company=self.company, system_key=Key.UNDEPOSITED_FUNDS
        ).update(is_fixed=False)

        call_command("backfill_system_keys", verbosity=0)

        self.assertFalse(
            ChartOfAccount.objects.get(
                company=self.company, system_key=Key.UNDEPOSITED_FUNDS
            ).is_fixed
        )

    def test_a_differently_named_account_is_not_swept_up(self):
        """Company 165 has an imported 'Import - Retained Earnings' beside the seeded one.

        It carries a real balance and is the tenant's own row. The backfill
        matches on the canonical title, so it must key the seeded account and
        leave the import alone.
        """
        ChartOfAccount.objects.filter(
            company=self.company, system_key=Key.RETAINED_EARNINGS
        ).update(system_key=None, is_fixed=False)
        imported = ChartOfAccount.objects.create(
            company=self.company,
            title="Import - Retained Earnings",
            code="80020",
            kind=ChartOfAccountKindChoices.EQUITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=9042.95,
        )

        call_command("backfill_system_keys", "--apply", verbosity=0)

        imported.refresh_from_db()
        self.assertIsNone(imported.system_key)
        self.assertFalse(imported.is_fixed)
        self.assertEqual(
            ChartOfAccount.objects.get(
                company=self.company, system_key=Key.RETAINED_EARNINGS
            ).title,
            "Retained Earnings",
        )

    def test_it_is_idempotent(self):
        call_command("backfill_system_keys", "--apply", verbosity=0)
        before = list(
            ChartOfAccount.objects.filter(company=self.company)
            .order_by("id")
            .values_list("id", "system_key", "is_fixed", "title")
        )

        call_command("backfill_system_keys", "--apply", verbosity=0)

        self.assertEqual(
            before,
            list(
                ChartOfAccount.objects.filter(company=self.company)
                .order_by("id")
                .values_list("id", "system_key", "is_fixed", "title")
            ),
        )
