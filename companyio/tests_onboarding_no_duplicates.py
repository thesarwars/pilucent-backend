"""Onboarding must never produce a duplicate account title.

`unique_title_per_company_ci` (accounts migration 0044) forbids two live accounts
sharing a title within one company. Company onboarding seeds 48-126 accounts
depending on industry, so it is by far the largest single batch of account
creation in the product and the one place a seed regression would surface as a
failed signup rather than a quiet duplicate.

The seeds are clean today. Gap #21 of `CHART_OF_ACCOUNTS_GAPS.md` recorded
duplicate titles in four industries -- `constructions`, `hardware_electronics`,
`restaurant_hotel`, `travel_tourism` -- and those were fixed before the constraint
landed. The 33 duplicate `Prepaid Insurance` rows the repair retired from
production in 2026-08 were residue from the older seed, not something onboarding
was still minting.

This exists so that stays true. A seed edit that reintroduces a duplicate title
-- in any case -- now fails here rather than at a customer's signup.
"""

from django.core.management import call_command
from django.db.models import Count
from django.db.models.functions import Upper
from django.test import TestCase

from accounts.models import ChartOfAccount

from companyio.choices import CompanyKindChoices
from companyio.models import Company


class OnboardingProducesNoDuplicatesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # The chart is seeded from the category tree, so it has to exist first.
        call_command("create_chart_of_account_category", verbosity=0)

    def duplicate_groups(self, company):
        return list(
            ChartOfAccount.objects.filter(company=company)
            .annotate(key=Upper("title"))
            .values("key")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .values_list("key", "n")
        )

    def test_every_industry_onboards_without_a_duplicate_title(self):
        """All 20 industries, case-insensitively.

        Case matters: the constraint is on UPPER(title), so "Prepaid Insurance"
        beside "prepaid insurance" is a collision the seed validator's
        case-sensitive check would pass.
        """
        for kind in CompanyKindChoices.values:
            with self.subTest(industry=kind):
                company = Company.objects.create(name=f"Probe {kind}", kind=kind)

                self.assertEqual(
                    self.duplicate_groups(company),
                    [],
                    f"{kind} seeds a duplicate title",
                )

    def test_onboarding_actually_seeds_accounts(self):
        """Guards the guard: a seed that creates nothing would pass the above."""
        company = Company.objects.create(
            name="Probe", kind=CompanyKindChoices.ECOMMERCE
        )

        self.assertGreater(
            ChartOfAccount.objects.filter(company=company).count(),
            40,
            "onboarding stopped seeding, so the duplicate check proves nothing",
        )

    def test_saving_a_company_again_does_not_reseed(self):
        """The other way a duplicate could appear: seeding twice."""
        company = Company.objects.create(
            name="Probe", kind=CompanyKindChoices.ECOMMERCE
        )
        before = ChartOfAccount.objects.filter(company=company).count()

        company.name = "Probe Renamed"
        company.save()

        self.assertEqual(
            ChartOfAccount.objects.filter(company=company).count(), before
        )
        self.assertEqual(self.duplicate_groups(company), [])

    def test_two_companies_may_seed_the_same_titles(self):
        """The constraint is per company, so onboarding two tenants is fine."""
        first = Company.objects.create(
            name="First", kind=CompanyKindChoices.ECOMMERCE
        )
        second = Company.objects.create(
            name="Second", kind=CompanyKindChoices.ECOMMERCE
        )

        self.assertEqual(self.duplicate_groups(first), [])
        self.assertEqual(self.duplicate_groups(second), [])
        self.assertEqual(
            ChartOfAccount.objects.filter(company=first).count(),
            ChartOfAccount.objects.filter(company=second).count(),
        )
