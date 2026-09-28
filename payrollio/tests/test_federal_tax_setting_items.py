from datetime import date

from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError

from companyio.models import Company
from payrollio.choicess import (
    PayrollFederalTaxInfoSettingChoices,
    PayrollFederalTaxInfoTaxFormChoices,
)
from payrollio.django_rest.helpers.federal_tax_setting_items import (
    MAX_FEDERAL_TAX_SCHEDULE_ITEMS,
    normalize_federal_tax_effective_date,
    normalize_tax_form,
    upsert_federal_tax_setting_item,
    validate_payment_frequency_value,
    validate_tax_form_payment_frequency,
    validate_tax_form_value,
)
from payrollio.models import PayrollFederalTaxInfoSetting


class FederalTaxEffectiveDateTests(SimpleTestCase):
    def test_form_941_monthly_snaps_jan_to_april(self):
        result = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
            PayrollFederalTaxInfoSettingChoices.MONTHLY,
            date(2025, 1, 1),
        )
        self.assertEqual(result, date(2025, 4, 1))

    def test_form_941_quarterly_keeps_quarter_start(self):
        result = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
            PayrollFederalTaxInfoSettingChoices.QUARTERLY,
            date(2025, 1, 1),
        )
        self.assertEqual(result, date(2025, 1, 1))

    def test_form_943_annual_snaps_to_january_first(self):
        result = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
            PayrollFederalTaxInfoSettingChoices.ANNUALLY,
            date(2025, 6, 15),
        )
        self.assertEqual(result, date(2025, 1, 1))

    def test_form_943_monthly_snaps_to_january_first(self):
        """Same slot as annual/semi-weekly so QB-style replace on 01-01-2025 works."""
        result = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
            PayrollFederalTaxInfoSettingChoices.MONTHLY,
            date(2025, 1, 1),
        )
        self.assertEqual(result, date(2025, 1, 1))

    def test_form_943_semi_weekly_same_slot_as_monthly_for_same_year(self):
        monthly = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
            PayrollFederalTaxInfoSettingChoices.MONTHLY,
            date(2025, 6, 15),
        )
        semi_weekly = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
            PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
            date(2025, 1, 1),
        )
        self.assertEqual(monthly, semi_weekly)
        self.assertEqual(monthly, date(2025, 1, 1))

    def test_form_944_always_snaps_to_january_first(self):
        result = normalize_federal_tax_effective_date(
            PayrollFederalTaxInfoTaxFormChoices.FORM_944_EACH_YEAR,
            PayrollFederalTaxInfoSettingChoices.ANNUALLY,
            date(2027, 3, 20),
        )
        self.assertEqual(result, date(2027, 1, 1))

    def test_form_944_allows_monthly_frequency(self):
        frequency = validate_tax_form_payment_frequency(
            PayrollFederalTaxInfoTaxFormChoices.FORM_944_EACH_YEAR,
            PayrollFederalTaxInfoSettingChoices.MONTHLY,
        )
        self.assertEqual(frequency, PayrollFederalTaxInfoSettingChoices.MONTHLY)

    def test_form_941_each_year_alias_normalizes(self):
        self.assertEqual(
            normalize_tax_form("FORM_941_EACH_YEAR"),
            PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
        )
        self.assertEqual(
            validate_tax_form_value("FORM_941_EACH_YEAR"),
            PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
        )

    def test_quaterly_typo_normalizes(self):
        self.assertEqual(
            validate_payment_frequency_value("quaterly"),
            PayrollFederalTaxInfoSettingChoices.QUARTERLY,
        )

    def test_missing_tax_form_raises(self):
        with self.assertRaises(ValidationError):
            validate_tax_form_value(None)


class FederalTaxUpsertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="Federal Tax Upsert Co",
            email="federal-tax-upsert@example.com",
        )
        cls.federal_setting = PayrollFederalTaxInfoSetting.objects.create(
            company=cls.company,
            ein_number="12-3456789",
        )

    def test_943_2027_does_not_replace_941_semi_weekly_same_date(self):
        """Form 943 and Form 941 on 2027-01-01 are separate schedule rows."""
        upsert_federal_tax_setting_item(
            self.federal_setting,
            tax_form=PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
            payment_frequency=PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
            effective_date=date(2027, 1, 1),
        )
        item_943, action = upsert_federal_tax_setting_item(
            self.federal_setting,
            tax_form=PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
            payment_frequency=PayrollFederalTaxInfoSettingChoices.MONTHLY,
            effective_date=date(2027, 1, 1),
        )
        self.assertEqual(action, "created")
        self.assertEqual(item_943.tax_form, PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR)
        self.assertEqual(item_943.payment_frequency, PayrollFederalTaxInfoSettingChoices.MONTHLY)
        self.assertEqual(item_943.effective_date, date(2027, 1, 1))

        items = self.federal_setting.items.all()
        self.assertEqual(items.count(), 2)
        forms = {item.tax_form: item.payment_frequency for item in items}
        self.assertEqual(
            forms[PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER],
            PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
        )
        self.assertEqual(
            forms[PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR],
            PayrollFederalTaxInfoSettingChoices.MONTHLY,
        )

    def test_941_2026_and_944_2026_are_separate_rows(self):
        """QB allows Form 941 and Form 944 both effective 01/01/2026."""
        upsert_federal_tax_setting_item(
            self.federal_setting,
            tax_form="FORM_941_EACH_YEAR",
            payment_frequency="semi_weekly",
            effective_date=date(2026, 1, 1),
        )
        item_944, action = upsert_federal_tax_setting_item(
            self.federal_setting,
            tax_form=PayrollFederalTaxInfoTaxFormChoices.FORM_944_EACH_YEAR,
            payment_frequency=PayrollFederalTaxInfoSettingChoices.MONTHLY,
            effective_date=date(2026, 1, 1),
        )
        self.assertEqual(action, "created")
        self.assertEqual(item_944.effective_date, date(2026, 1, 1))

        items = self.federal_setting.items.all()
        self.assertEqual(items.count(), 2)
        by_form = {item.tax_form: item.payment_frequency for item in items}
        self.assertEqual(
            by_form[PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER],
            PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
        )
        self.assertEqual(
            by_form[PayrollFederalTaxInfoTaxFormChoices.FORM_944_EACH_YEAR],
            PayrollFederalTaxInfoSettingChoices.MONTHLY,
        )

    def test_max_four_schedules_evicts_oldest_when_full(self):
        base_date = date(2020, 1, 1)
        for offset in range(MAX_FEDERAL_TAX_SCHEDULE_ITEMS):
            upsert_federal_tax_setting_item(
                self.federal_setting,
                tax_form=PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
                payment_frequency=PayrollFederalTaxInfoSettingChoices.QUARTERLY,
                effective_date=date(base_date.year + offset, 1, 1),
            )
        oldest = date(base_date.year, 1, 1)
        self.assertTrue(
            self.federal_setting.items.filter(effective_date=oldest).exists()
        )

        item, action = upsert_federal_tax_setting_item(
            self.federal_setting,
            tax_form=PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
            payment_frequency=PayrollFederalTaxInfoSettingChoices.MONTHLY,
            effective_date=date(2030, 1, 1),
        )
        self.assertEqual(action, "created")
        self.assertEqual(self.federal_setting.items.count(), MAX_FEDERAL_TAX_SCHEDULE_ITEMS)
        self.assertFalse(
            self.federal_setting.items.filter(effective_date=oldest).exists()
        )
        self.assertEqual(item.effective_date, date(2030, 1, 1))
