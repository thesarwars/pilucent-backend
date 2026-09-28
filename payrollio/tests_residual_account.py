"""A deduction with no configured account made the pay run post short.

`_post_other_liability_withholding` is the fallback for deductions that reach no
configured liability account. It resolved "Payroll Liabilities" **by its literal
title**, and when that returned nothing it logged

    "the journal entry will not balance"

and returned -- leaving the wage debit carrying the deduction with no matching
credit. `assert_entry_balances` logs rather than raising (deliberately, while
other document types are still producing unbalanced entries), so the short entry
committed.

That was not a rare path. Only 15 of 20 industry templates ship a
"Payroll Liabilities" row, and only **17 of 60 production companies** have one,
so for the other 43 the fallback could never resolve.

Two fixes in one:

* **Resolved by `system_key`**, so renaming the account no longer breaks the pay
  run. That was the point of the exercise -- it is one of the accounts a blanket
  `is_fixed` was accidentally protecting, and the reason narrowing that flag
  (#33) could not ship.
* **Created on demand** rather than reported missing. A residual account that
  does not exist is not a reason to write a broken journal entry.

It is an ON_DEMAND key, not part of the required spine: five templates have no
such row, so demanding it at onboarding would report those industries as unable
to post when they can.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices as Status,
    ChartOfAccountSystemKeyChoices as Key,
)
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import (
    ON_DEMAND_KEYS,
    TITLE_TO_SYSTEM_KEY,
    missing_system_keys,
)

from companyio.choices import CompanyKindChoices
from companyio.models import Company

from weapi.django_rest.helpers.salary_process_journal_entry import (
    PAYROLL_RESIDUAL_TITLE,
    get_or_create_payroll_residual_account,
)


class ResidualAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def company(self, kind=CompanyKindChoices.ECOMMERCE, name="Acme"):
        return Company.objects.create(name=name, kind=kind)

    def test_it_is_created_when_the_company_has_none(self):
        """The 43-of-60 case: no such account exists at all."""
        company = self.company(kind=CompanyKindChoices.CONSTRUCTION)
        ChartOfAccount.objects.filter(
            company=company, title=PAYROLL_RESIDUAL_TITLE
        ).delete()

        account = get_or_create_payroll_residual_account(company)

        self.assertIsNotNone(account)
        self.assertEqual(account.system_key, Key.PAYROLL_LIABILITIES)
        self.assertEqual(account.kind, ChartOfAccountKindChoices.LIABILITIES)
        self.assertEqual(account.status, Status.ACTIVE)

    def test_it_adopts_an_existing_unkeyed_account(self):
        """The 17-of-60 case: a legacy company whose seeded row predates the key.

        New companies now get the key at seed time, because the title is in
        `TITLE_TO_SYSTEM_KEY` and the seeder reads it. This reproduces the state
        the existing 17 are in: the account is there, the key is not.
        """
        company = self.company()
        existing = ChartOfAccount.objects.get(
            company=company, title=PAYROLL_RESIDUAL_TITLE
        )
        ChartOfAccount.objects.filter(pk=existing.pk).update(
            system_key=None, is_fixed=False
        )

        account = get_or_create_payroll_residual_account(company)

        self.assertEqual(account.pk, existing.pk)
        self.assertEqual(account.system_key, Key.PAYROLL_LIABILITIES)
        self.assertTrue(account.is_fixed)
        self.assertEqual(
            ChartOfAccount.objects.filter(
                company=company, title=PAYROLL_RESIDUAL_TITLE
            ).count(),
            1,
            "a second residual account was created beside the existing one",
        )

    def test_it_is_idempotent(self):
        company = self.company()

        first = get_or_create_payroll_residual_account(company)
        second = get_or_create_payroll_residual_account(company)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            ChartOfAccount.objects.filter(
                company=company, system_key=Key.PAYROLL_LIABILITIES
            ).count(),
            1,
        )

    def test_a_rename_no_longer_breaks_resolution(self):
        """The whole point: identity, not the label the user owns."""
        company = self.company()
        account = get_or_create_payroll_residual_account(company)

        account.title = "Payroll Clearing Account"
        account.save(update_fields=["title"])

        self.assertEqual(
            get_or_create_payroll_residual_account(company).pk, account.pk
        )

    def test_a_removed_account_is_not_reused(self):
        company = self.company()
        retired = get_or_create_payroll_residual_account(company)
        retired.status = Status.REMOVED
        retired.save(update_fields=["status"])

        replacement = get_or_create_payroll_residual_account(company)

        self.assertNotEqual(replacement.pk, retired.pk)
        self.assertEqual(replacement.status, Status.ACTIVE)

    def test_it_works_for_every_industry(self):
        """Five templates ship no such row; none may fail."""
        for kind in CompanyKindChoices.values:
            with self.subTest(industry=kind):
                company = self.company(kind=kind, name=f"Probe {kind}")
                account = get_or_create_payroll_residual_account(company)

                self.assertIsNotNone(account, f"{kind} could not get one")
                self.assertEqual(account.system_key, Key.PAYROLL_LIABILITIES)


    def test_a_new_company_is_seeded_with_it_already_keyed(self):
        """Since the title is in the map, the seeder stamps it -- no repair needed."""
        company = self.company(name="Fresh")

        account = ChartOfAccount.objects.filter(
            company=company, system_key=Key.PAYROLL_LIABILITIES
        ).first()

        self.assertIsNotNone(account)
        self.assertEqual(account.title, PAYROLL_RESIDUAL_TITLE)


class KeyRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def test_the_title_resolves_to_the_key(self):
        self.assertEqual(
            TITLE_TO_SYSTEM_KEY[PAYROLL_RESIDUAL_TITLE], Key.PAYROLL_LIABILITIES
        )

    def test_it_is_on_demand_not_part_of_the_spine(self):
        """Five templates have no such row; onboarding must not demand it."""
        self.assertIn(Key.PAYROLL_LIABILITIES, ON_DEMAND_KEYS)

    def test_onboarding_does_not_report_it_missing(self):
        for kind in (
            CompanyKindChoices.CONSTRUCTION,   # template has no such row
            CompanyKindChoices.ECOMMERCE,      # template does
        ):
            with self.subTest(industry=kind):
                company = Company.objects.create(name=f"C {kind}", kind=kind)
                self.assertNotIn(
                    Key.PAYROLL_LIABILITIES, missing_system_keys(company)
                )


class CallSiteTests(TestCase):
    def test_the_posting_path_no_longer_resolves_by_title(self):
        import inspect

        from weapi.django_rest.helpers import salary_process_journal_entry

        source = inspect.getsource(
            salary_process_journal_entry._post_other_liability_withholding
        )

        self.assertIn("get_or_create_payroll_residual_account(company)", source)
        self.assertNotIn("get_chart_of_account(", source)

    def test_the_short_entry_branch_is_gone(self):
        """It logged 'will not balance' and returned. There is nothing to return for now."""
        import inspect

        from weapi.django_rest.helpers import salary_process_journal_entry

        source = inspect.getsource(
            salary_process_journal_entry._post_other_liability_withholding
        )

        self.assertNotIn("The journal entry will not balance", source)
