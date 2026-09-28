"""Two defects found by re-reviewing #33, both live without it.

**The two federal payroll tax accounts were resolved by title alone.** My own
commit `38d1ff3c` argued they did not need keys because "their titles are
per-state, which system keys would not scale to". That is true of
`STATE_TAX_LIABILITY_COMPONENTS` (NY, MN) and false of the federal ones:

    FEDERAL_TAX_LIABILITY_COMPONENTS = (
        (FEDERAL_TAX_GROUP_941, "Federal Taxes (941/943/944)"),
        (FEDERAL_TAX_GROUP_940, "Federal Unemployment (940)"),
    )

A flat tuple -- the same two strings on every company, seeded by 19 of 20
templates. Renaming one skips the component, and the pay run then omits that
credit with only a log line; `assert_entry_balances` logs rather than raising,
so the short entry commits.

Worse, and self-inflicted: `get_company_chart_account` filters `status=ACTIVE`,
and the deactivate endpoint refuses only accounts with a `system_key`. These had
none, so **deactivating one broke payroll component creation** -- a vector the
blanket `is_fixed` had been accidentally blocking until deactivation shipped.

**`update()` never re-derived `kind` from a changed `account_type`.** Only
`create()` did. The model's guard refuses reclassification of an account that
*has* posted lines, so a not-yet-posted account could be retyped freely and the
pair silently diverged -- the statement engines bucket on `account_type` while
most other code reads `kind`, so an account whose two disagree belongs to no
section of either statement.
"""

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices as Status,
    ChartOfAccountSystemKeyChoices as Key,
)
from accounts.models import ChartOfAccount, User

from common.django_rest.helpers.chart_of_account_helpers import (
    ON_DEMAND_KEYS,
    TITLE_TO_SYSTEM_KEY,
    missing_system_keys,
)

from companyio.choices import CompanyKindChoices
from companyio.models import Company, CompanyUser

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    FEDERAL_TAX_LIABILITY_COMPONENTS,
    get_company_chart_account,
)

from rest_framework.exceptions import ValidationError


FEDERAL_941 = "Federal Taxes (941/943/944)"
FEDERAL_940 = "Federal Unemployment (940)"


class FederalTitlesAreGlobalTests(TestCase):
    def test_the_federal_components_are_not_per_state(self):
        """The premise of the mistake, pinned so it cannot be repeated.

        `STATE_TAX_LIABILITY_COMPONENTS` is a dict keyed by state.
        `FEDERAL_TAX_LIABILITY_COMPONENTS` is a flat tuple, so its titles are
        the same on every company -- which is exactly what a system key is for.
        """
        titles = {title for _key, title in FEDERAL_TAX_LIABILITY_COMPONENTS}

        self.assertEqual(titles, {FEDERAL_941, FEDERAL_940})

    def test_both_are_keyed(self):
        self.assertEqual(TITLE_TO_SYSTEM_KEY[FEDERAL_941], Key.FEDERAL_TAX_941)
        self.assertEqual(
            TITLE_TO_SYSTEM_KEY[FEDERAL_940], Key.FEDERAL_UNEMPLOYMENT_940
        )

    def test_they_are_on_demand_not_spine(self):
        """`food_beverage` ships neither, and ~27 of 60 companies have none."""
        for key in (Key.FEDERAL_TAX_941, Key.FEDERAL_UNEMPLOYMENT_940):
            with self.subTest(key=key):
                self.assertIn(key, ON_DEMAND_KEYS)


class FederalAccountResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(
            name="Acme", kind=CompanyKindChoices.ECOMMERCE
        )

    def federal(self):
        return ChartOfAccount.objects.filter(
            company=self.company, title=FEDERAL_941
        ).first()

    def test_onboarding_does_not_report_them_missing(self):
        missing = missing_system_keys(self.company)

        self.assertNotIn(Key.FEDERAL_TAX_941, missing)
        self.assertNotIn(Key.FEDERAL_UNEMPLOYMENT_940, missing)

    def test_resolution_keys_an_unkeyed_account_on_first_use(self):
        account = self.federal()
        self.assertIsNotNone(account, "the ecommerce template should seed it")
        ChartOfAccount.objects.filter(pk=account.pk).update(
            system_key=None, is_fixed=False
        )

        resolved = get_company_chart_account(self.company, FEDERAL_941)

        self.assertEqual(resolved.pk, account.pk)
        resolved.refresh_from_db()
        self.assertEqual(resolved.system_key, Key.FEDERAL_TAX_941)
        self.assertTrue(resolved.is_fixed)

    def test_a_rename_no_longer_loses_it(self):
        """The defect: the pay run posted short by the whole federal withholding."""
        account = self.federal()
        get_company_chart_account(self.company, FEDERAL_941)  # key it

        account.refresh_from_db()
        account.title = "Federal Withholding"
        account.save(update_fields=["title"])

        self.assertEqual(
            get_company_chart_account(self.company, FEDERAL_941).pk, account.pk
        )

    def test_a_missing_account_still_resolves_to_none(self):
        """Deliberately unchanged -- auto-create is not this function's call."""
        ChartOfAccount.objects.filter(
            company=self.company, title__in=[FEDERAL_941, FEDERAL_940]
        ).delete()

        self.assertIsNone(get_company_chart_account(self.company, FEDERAL_941))

    def test_deactivation_is_now_refused(self):
        """The vector deactivation opened, and the reason it opened.

        COA-153 gates on `system_key`. These had none, so a tenant could retire
        the account and payroll component creation stopped finding it -- the
        resolver filters `status=ACTIVE`.
        """
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDeactivate,
        )

        user = User.objects.create_user(
            name="A", email="fed@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=user, company=self.company)
        get_company_chart_account(self.company, FEDERAL_941)  # key it
        account = self.federal()

        view = PrivateWeChartOfAccountDeactivate()
        view.kwargs = {"uid": str(account.uid)}
        view.request = type("R", (), {"user": user, "data": {}})()

        with self.assertRaises(ValidationError) as caught:
            view.post(view.request)

        self.assertIn("COA-153", str(caught.exception))

    def test_an_unrelated_title_is_unaffected(self):
        """Only mapped titles take the key path."""
        other = ChartOfAccount.objects.create(
            company=self.company, title="Some Other Liability", code="2999",
            kind=ChartOfAccountKindChoices.LIABILITIES, status=Status.ACTIVE,
        )

        resolved = get_company_chart_account(self.company, "Some Other Liability")

        self.assertEqual(resolved.pk, other.pk)
        resolved.refresh_from_db()
        self.assertIsNone(resolved.system_key)
        self.assertFalse(resolved.is_fixed)


class RetypeDerivesKindTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme", kind=CompanyKindChoices.ECOMMERCE
        )
        cls.user = User.objects.create_user(
            name="A", email="retype@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def account(self):
        return ChartOfAccount.objects.create(
            company=self.company, title="Tenant Account", code="6994",
            kind=ChartOfAccountKindChoices.EXPENSES, status=Status.ACTIVE,
            is_fixed=False,
        )

    def category(self, title):
        from categoryio.models import Category

        return Category.objects.filter(title=title, parent__isnull=False).first()

    def serializer(self, instance, data):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )

        return S(
            instance=instance, data=data, partial=True,
            context={"request": type("R", (), {"user": self.user})()},
        )

    def test_retyping_moves_kind_with_the_account_type(self):
        account = self.account()
        bank = self.category("Bank")
        self.assertIsNotNone(bank, "taxonomy missing 'Bank'")

        serializer = self.serializer(account, {"account_type_slug": bank.slug})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        account.refresh_from_db()
        self.assertEqual(account.account_type_id, bank.pk)
        self.assertEqual(
            account.kind,
            ChartOfAccountKindChoices.ASSETS,
            "kind stayed behind, so the account belongs to no statement section",
        )

    def test_the_pair_never_disagrees_after_an_update(self):
        from common.django_rest.helpers.chart_of_account_helpers import (
            derive_account_kind,
        )

        account = self.account()
        for title in ("Bank", "Other Current Liabilities", "Equity"):
            category = self.category(title)
            if category is None:
                continue
            with self.subTest(account_type=title):
                serializer = self.serializer(
                    account, {"account_type_slug": category.slug}
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()

                account.refresh_from_db()
                self.assertEqual(
                    account.kind, derive_account_kind(account.account_type)
                )

    def test_an_update_that_does_not_retype_leaves_kind_alone(self):
        account = self.account()

        serializer = self.serializer(account, {"description": "just a note"})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        account.refresh_from_db()
        self.assertEqual(account.kind, ChartOfAccountKindChoices.EXPENSES)
