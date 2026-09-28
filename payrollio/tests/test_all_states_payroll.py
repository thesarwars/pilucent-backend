"""All-states payroll rollout: the NY/MN gate is gone.

Covers the three layers that used to be pinned to NY/MN:
- normalize_us_state now validates against the full USPS code list;
- accounting-preferences component seeding falls back to a generic
  {ST}_INCOME_TAX / {ST}_UNEMPLOYMENT_TAXES pair for non-NY/MN states;
- journal payroll_type expansion matches an arbitrary state's components.

NY/MN behavior must be bit-identical (their override tuples are untouched).
"""

from decimal import Decimal

import unittest

from django.test import TestCase

from common.test_support import PreConstraintDataMixin

from accounts.choices import ChartOfAccountKindChoices
from accounts.models import ChartOfAccount

from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices
from categoryio.models import Category

from payrollio.choicess import AccountingPreferencesExpenseTypeChoices
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    STATE_TAX_LIABILITY_COMPONENTS,
    US_STATE_CODES,
    _chart_title_for_tax_account_type,
    _generic_state_components,
    _is_generic_state_component,
    _tax_liability_components_for_state,
    ensure_tax_liability_component,
    normalize_us_state,
    sync_tax_liability_components,
)
from payrollio.django_rest.helpers.payroll_onboarding import (
    ensure_state_tax_info_setting,
)
from payrollio.models import PayrollAccountExpenseAccountComponent
from payrollio.models import PayrollAccountingPreferencesSetting
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAX_GROUP_940,
    FEDERAL_TAX_GROUP_941,
    TAX_GROUP_PAYROLL_TYPES,
    payroll_types_for_group,
    state_employment_tax_group_key,
    state_income_tax_group_key,
    sum_payroll_components,
)


class NormalizeUsStateTests(unittest.TestCase):
    def test_code_passthrough_and_case(self):
        self.assertEqual(normalize_us_state("CA"), "CA")
        self.assertEqual(normalize_us_state("ca"), "CA")
        self.assertEqual(normalize_us_state(" tx "), "TX")

    def test_full_names_map_for_all_states(self):
        self.assertEqual(normalize_us_state("California"), "CA")
        self.assertEqual(normalize_us_state("NEW YORK"), "NY")
        self.assertEqual(normalize_us_state("NYS"), "NY")  # stored-data variant
        self.assertEqual(normalize_us_state("Minnesota"), "MN")
        self.assertEqual(normalize_us_state("District of Columbia"), "DC")

    def test_garbage_returns_none(self):
        self.assertIsNone(normalize_us_state("XX"))
        self.assertIsNone(normalize_us_state("CALIFORNIAA"))
        self.assertIsNone(normalize_us_state(""))
        self.assertIsNone(normalize_us_state(None))

    def test_code_list_is_51(self):
        self.assertEqual(len(US_STATE_CODES), 51)  # 50 states + DC


class ComponentSeedingTests(unittest.TestCase):
    def test_ny_mn_keep_bespoke_tuples(self):
        ny = _tax_liability_components_for_state("NY", include_federal=False)
        self.assertEqual(list(ny), list(STATE_TAX_LIABILITY_COMPONENTS["NY"]))
        mn = _tax_liability_components_for_state("MN", include_federal=False)
        self.assertEqual(list(mn), list(STATE_TAX_LIABILITY_COMPONENTS["MN"]))

    def test_generic_state_gets_income_and_unemployment_pair(self):
        components = _tax_liability_components_for_state("CA", include_federal=False)
        self.assertEqual(
            components,
            [
                ("CA_INCOME_TAX", "CA Income Tax"),
                ("CA_UNEMPLOYMENT_TAXES", "CA Unemployment Taxes"),
            ],
        )

    def test_federal_always_included_when_asked(self):
        components = _tax_liability_components_for_state("GA", include_federal=True)
        account_types = [at for at, _ in components]
        self.assertIn(FEDERAL_TAX_GROUP_941, account_types)
        self.assertIn(FEDERAL_TAX_GROUP_940, account_types)
        self.assertIn("GA_INCOME_TAX", account_types)

    def test_no_income_tax_states_seed_unemployment_only(self):
        for state in ("TX", "FL", "WA"):
            components = _tax_liability_components_for_state(
                state, include_federal=False
            )
            self.assertEqual(
                components,
                [(f"{state}_UNEMPLOYMENT_TAXES", f"{state} Unemployment Taxes")],
            )

    def test_invalid_state_seeds_federal_only(self):
        components = _tax_liability_components_for_state("ZZ", include_federal=True)
        self.assertEqual(len(components), 2)  # the two federal groups
        self.assertEqual(_tax_liability_components_for_state(None, include_federal=False), [])

    def test_generic_component_keys_match_journal_group_keys(self):
        # The seeded account_type must equal the group key the journal poster
        # synthesizes, or credits would never find their account.
        for state in ("CA", "GA", "CO", "VA"):  # income-tax states
            seeded = [at for at, _ in _generic_state_components(state)]
            self.assertIn(state_income_tax_group_key(state), seeded)
            self.assertIn(state_employment_tax_group_key(state), seeded)
        for state in ("TX", "WA", "FL"):  # no-income-tax states
            seeded = [at for at, _ in _generic_state_components(state)]
            self.assertIn(state_employment_tax_group_key(state), seeded)

    def test_chart_title_resolution_generic_and_override(self):
        self.assertEqual(
            _chart_title_for_tax_account_type("CA", "CA_INCOME_TAX"), "CA Income Tax"
        )
        self.assertEqual(
            _chart_title_for_tax_account_type("NY", "NYS_INCOME_TAX"), "NYS Income Tax"
        )
        self.assertIsNone(_chart_title_for_tax_account_type("CA", "NYS_INCOME_TAX"))
        self.assertIsNone(_chart_title_for_tax_account_type(None, "CA_INCOME_TAX"))

    def test_is_generic_state_component(self):
        self.assertTrue(_is_generic_state_component("CA_INCOME_TAX"))
        self.assertTrue(_is_generic_state_component("WA_UNEMPLOYMENT_TAXES"))
        # NY/MN are override states -> not generic (no auto-create change)
        self.assertFalse(_is_generic_state_component("MN_INCOME_TAX"))
        self.assertFalse(_is_generic_state_component("NYS_INCOME_TAX"))
        self.assertFalse(_is_generic_state_component("ZZ_INCOME_TAX"))
        self.assertFalse(_is_generic_state_component("MN_PAID_LEAVE"))


class PayrollTypeExpansionTests(unittest.TestCase):
    def test_explicit_dict_entries_unchanged(self):
        for key, expected in TAX_GROUP_PAYROLL_TYPES.items():
            self.assertEqual(payroll_types_for_group(key), expected)

    def test_generic_income_includes_engine_bare_key(self):
        self.assertEqual(
            payroll_types_for_group("CA_INCOME_TAX"),
            ("CA_INCOME_TAX", "_INCOME_TAX"),
        )

    def test_generic_employment_includes_ui_employer_variants(self):
        self.assertEqual(
            payroll_types_for_group("CA_UNEMPLOYMENT_TAXES"),
            ("CA_UNEMPLOYMENT_TAXES", "CA_UI_EMPLOYER", "CA_SUI_EMPLOYER"),
        )

    def test_unknown_key_falls_back_to_itself(self):
        self.assertEqual(payroll_types_for_group("SOMETHING_ELSE"), ("SOMETHING_ELSE",))
        self.assertEqual(payroll_types_for_group(None), ())

    def test_generic_state_credit_sums_engine_components(self):
        # A CA run: engine emits the bare _INCOME_TAX withholding key and a
        # CA_UI_EMPLOYER employer line — both must land in their groups.
        components = [
            {"payroll_type": "_INCOME_TAX", "current": 250, "payroll_category": "EMPLOYEE_TAXES"},
            {"payroll_type": "CA_UI_EMPLOYER", "current": 90, "payroll_category": "EMPLOYER_TAXES"},
        ]
        income = sum_payroll_components(
            components, payroll_types=payroll_types_for_group("CA_INCOME_TAX")
        )
        employment = sum_payroll_components(
            components, payroll_types=payroll_types_for_group("CA_UNEMPLOYMENT_TAXES")
        )
        self.assertEqual(income, Decimal("250"))
        self.assertEqual(employment, Decimal("90"))


class OnboardingIntegrationTests(PreConstraintDataMixin, TestCase):
    """DB-backed coverage of the de-gated onboarding + auto-create wiring."""

    @classmethod
    def setUpTestData(cls):
        from companyio.models import Company

        cls.company = Company.objects.create(name="AllStates Inc")

        # Category tree required by _create_other_current_liability_chart_account
        liabilities = Category.objects.create(
            title="Liabilities",
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
            status=CategoryStatusChoices.ACTIVE,
        )
        cls.ocl_type = Category.objects.create(
            title="Other Current Liabilities",
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
            status=CategoryStatusChoices.ACTIVE,
            parent=liabilities,
        )
        cls.ocl_detail = Category.objects.create(
            title="Other Current Liability",
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
            status=CategoryStatusChoices.ACTIVE,
            parent=cls.ocl_type,
        )

    def _make_settings(self):
        account = ChartOfAccount.objects.create(
            code="1000", title="Cash on Hand", company=self.company
        )
        return PayrollAccountingPreferencesSetting.objects.create(
            company=self.company,
            paycheck_payroll_tax_expense_account=account,
            global_wage_account=account,
            global_contribution_expense_account=account,
            global_employer_tax_expenses=account,
            wage_expense_type=AccountingPreferencesExpenseTypeChoices.SINGLE_WAGE_ACCOUNT,
            company_contribution_expense_type=(
                AccountingPreferencesExpenseTypeChoices.COMPANY_CONTRIBUTION_SINGLE_ACCOUNT
            ),
            employer_tax_expense_type=(
                AccountingPreferencesExpenseTypeChoices.SINGLE_EMPLOYER_TAX_ACCOUNT
            ),
            tax_liability_expense_type=(
                AccountingPreferencesExpenseTypeChoices.DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP
            ),
            other_liability_asset_account=(
                AccountingPreferencesExpenseTypeChoices.OTHER_LIABILITY_ASSETS_TYPE
            ),
        )

    def test_state_tax_info_created_for_any_state(self):
        # The old SUPPORTED_PAYROLL_STATES gate returned None for CA.
        setting = ensure_state_tax_info_setting(self.company, "California")
        self.assertIsNotNone(setting)
        self.assertEqual(setting.state, "CA")

    def test_state_tax_info_rejects_garbage(self):
        self.assertIsNone(ensure_state_tax_info_setting(self.company, "XX"))
        self.assertIsNone(ensure_state_tax_info_setting(self.company, None))

    def test_ensure_component_auto_creates_liability_account_for_generic_state(self):
        settings = self._make_settings()
        account = ensure_tax_liability_component(
            settings, self.company, "CA_INCOME_TAX", state="CA"
        )
        self.assertIsNotNone(account)
        self.assertEqual(account.title, "CA Income Tax")
        self.assertEqual(account.kind, ChartOfAccountKindChoices.LIABILITIES)
        component = PayrollAccountExpenseAccountComponent.objects.get(
            payroll_accounting_preferences=settings, account_type="CA_INCOME_TAX"
        )
        self.assertEqual(component.expense_account, account)

    def test_generic_state_never_binds_non_liability_account(self):
        # A same-titled EXPENSES account (e.g. corporate state tax expense)
        # must not receive payroll withholding credits.
        settings = self._make_settings()
        expense = ChartOfAccount.objects.create(
            code="6100",
            title="CA Income Tax",
            company=self.company,
            kind=ChartOfAccountKindChoices.EXPENSES,
        )
        account = ensure_tax_liability_component(
            settings, self.company, "CA_INCOME_TAX", state="CA"
        )
        self.assertIsNotNone(account)
        self.assertNotEqual(account.pk, expense.pk)
        self.assertEqual(account.kind, ChartOfAccountKindChoices.LIABILITIES)

    def test_sync_seeds_generic_state_components(self):
        settings = self._make_settings()
        created = sync_tax_liability_components(
            settings, self.company, "CA", include_federal=False
        )
        account_types = sorted(c.account_type for c in created)
        self.assertEqual(account_types, ["CA_INCOME_TAX", "CA_UNEMPLOYMENT_TAXES"])
