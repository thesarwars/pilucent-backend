"""The rules in force on a date -- with the window actually read -- and a gate
that throws.

Two defects this replaces. `payrollio.PayrollTaxConfig` carried
`effective_from`/`effective_to` that nothing read, so "the rules on date D" was
whichever row came first. And the prototype let a value nobody had verified
reach a released payslip: confidence was a comment, not a state. Doc §1.1,
§1.2, §1.5 and acceptance test 12.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from rulebookio.book import (
    NoRuleSetInForce,
    RuleNotProductionSafe,
    UnknownRule,
    require_production_safe,
    rule_book,
)
from rulebookio.models import RuleSet
from rulebookio.seed_bd import assert_enum_coverage, rule_sets
from rulebookio.test_support import seed_rules


class RuleBookWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()

    def test_the_income_year_decides_the_tax_set(self):
        self.assertEqual(rule_book(date(2026, 7, 1)).tax.version, "2026-27")
        self.assertEqual(rule_book(date(2026, 7, 1)).tax.value("taxFreeThresholds.GENERAL"), 400000)
        self.assertEqual(rule_book(date(2026, 6, 30)).tax.version, "2025-26")
        self.assertEqual(rule_book(date(2026, 6, 30)).tax.value("taxFreeThresholds.GENERAL"), 375000)

    def test_a_year_with_no_set_throws_instead_of_borrowing_a_neighbour(self):
        """rules.js defines no 2027-28 card. The wrong year's slabs reaching a
        payslip is exactly the silent fallback this refuses."""
        with self.assertRaises(NoRuleSetInForce) as caught:
            rule_book(date(2027, 7, 1)).tax.get("slabs")
        self.assertIn("2027-07-01", str(caught.exception))

    def test_the_labour_amendment_applies_from_its_effective_date(self):
        self.assertEqual(rule_book(date(2026, 4, 9)).labour.value("festivalHolidayDays"), 11)
        self.assertEqual(rule_book(date(2026, 4, 10)).labour.value("festivalHolidayDays"), 13)

    def test_a_retired_set_is_not_in_force(self):
        RuleSet.objects.filter(family="TAX", version="2026-27").update(status="RETIRED")
        with self.assertRaises(NoRuleSetInForce):
            rule_book(date(2026, 12, 1)).tax.get("slabs")

    def test_an_unknown_rule_throws_and_names_itself(self):
        with self.assertRaises(UnknownRule) as caught:
            rule_book(date(2026, 12, 1)).tax.get("taxFreeThresholds.NOBODY")
        self.assertIn("tax.2026-27.taxFreeThresholds.NOBODY", str(caught.exception))

    def test_a_group_is_not_a_rule(self):
        with self.assertRaises(UnknownRule):
            rule_book(date(2026, 12, 1)).tax.get("taxFreeThresholds")

    def test_the_employment_exemption_is_one_third_not_0_3333(self):
        """0.3333 understates the exemption; the statute says one third."""
        from common.money import apply_rate

        third = rule_book(date(2026, 12, 1)).tax.value("employmentExemptionFraction")
        self.assertEqual(third, "1/3")
        self.assertEqual(apply_rate(900000, third), Decimal(300000))

    def test_slabs_are_band_widths_not_thresholds(self):
        """rules.js: 35% applies above total income of Tk 30,000,000 in 2028-29.
        That only holds if the slab figures are widths laid end to end."""
        book = rule_book(date(2028, 12, 1))
        widths = [band["width"] for band in book.tax.value("slabs")[:-1]]
        self.assertEqual(sum(widths) + book.tax.value("taxFreeThresholds.GENERAL"), 30_000_000)


class ReleaseGateTests(TestCase):
    """Acceptance test 12."""

    @classmethod
    def setUpTestData(cls):
        seed_rules()

    def setUp(self):
        self.book = rule_book(date(2027, 3, 8))

    def test_a_drafted_value_throws_and_names_the_rule(self):
        floors = self.book.labour.get("gradeWageFloors")
        self.assertEqual(floors.confidence, "DRAFTED")
        with self.assertRaises(RuleNotProductionSafe) as caught:
            require_production_safe(floors)
        self.assertIn("labour.2026-04-10.gradeWageFloors", str(caught.exception))
        self.assertIn("drafted", str(caught.exception))
        self.assertEqual(caught.exception.rule, "labour.2026-04-10.gradeWageFloors")

    def test_corroborated_and_disputed_do_not_pass_either(self):
        for path in ("festivalBonusesPerYear", "compensationDaysPerYearBySeparationType.RESIGNATION"):
            with self.subTest(path=path), self.assertRaises(RuleNotProductionSafe):
                require_production_safe(self.book.labour.get(path))

    def test_a_value_nobody_has_supplied_does_not_pass(self):
        with self.assertRaises(RuleNotProductionSafe) as caught:
            require_production_safe(self.book.tax.get("wppfExemption"))
        self.assertIn("has no value", str(caught.exception))

    def test_a_verified_value_passes(self):
        self.assertEqual(require_production_safe(self.book.tax.get("taxFreeThresholds.FEMALE")), 450000)


class SeedTests(TestCase):
    def test_seeding_twice_updates_in_place(self):
        seed_rules()
        seed_rules()
        self.assertEqual(RuleSet.objects.count(), 6)

    def test_every_enum_value_has_a_rule(self):
        sets = rule_sets()
        assert_enum_coverage(sets)
        del sets[1]["data"]["taxFreeThresholds"]["THIRD_GENDER"]
        with self.assertRaises(ValueError):
            assert_enum_coverage(sets)
