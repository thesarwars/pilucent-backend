from decimal import Decimal

import unittest

from payrollio.django_rest.helpers.payroll_journal_mappings import (
    TAX_GROUP_PAYROLL_TYPES,
    net_pay_from_components,
    payroll_type_matches_other_liability,
    quantize_money,
    sum_payroll_components,
)
from payrollio.django_rest.helpers.tax_ein_sync import federal_ein_value, normalize_ein


class PayrollJournalMappingsTests(unittest.TestCase):
    def test_mn_unemployment_rollup_sums_granular_employer_types(self):
        components = [
            {"payroll_type": "MN_UI_EMPLOYER", "current": 176, "payroll_category": "EMPLOYER_TAXES"},
            {"payroll_type": "MN_WORKFORCE_DEVELOPMENT_FEE", "current": 40, "payroll_category": "EMPLOYER_TAXES"},
            {"payroll_type": "MN_ADDITIONAL_ASSESSMENT", "current": 25, "payroll_category": "EMPLOYER_TAXES"},
            {"payroll_type": "MN_PAID_LEAVE_EMPLOYER", "current": 176, "payroll_category": "EMPLOYER_TAXES"},
        ]
        total = sum_payroll_components(
            components,
            payroll_types=TAX_GROUP_PAYROLL_TYPES["MN_UNEMPLOYMENT_TAXES"],
        )
        self.assertEqual(total, Decimal("417"))

    def test_federal_941_includes_employee_and_employer_fica(self):
        components = [
            {"payroll_type": "FEDERAL_INCOME_TAX", "current": 100, "payroll_category": "EMPLOYEE_TAXES"},
            {"payroll_type": "SOCIAL_SECURITY", "current": 50, "payroll_category": "EMPLOYEE_TAXES"},
            {"payroll_type": "SOCIAL_SECURITY_EMPLOYER", "current": 50, "payroll_category": "EMPLOYER_TAXES"},
        ]
        total = sum_payroll_components(
            components,
            payroll_types=TAX_GROUP_PAYROLL_TYPES["FEDERAL_TAXES_(941/943/944)"],
        )
        self.assertEqual(total, Decimal("200"))

    def test_health_ins_alias_matches_deduction_title(self):
        self.assertTrue(
            payroll_type_matches_other_liability("Health Insurance", "Health Ins.")
        )
        self.assertTrue(
            payroll_type_matches_other_liability("Health Ins.", "Health Insurance")
        )

    def test_ny_income_and_rsf_map_to_liability_groups(self):
        components = [
            {
                "payroll_type": "_INCOME_TAX",
                "current": 3595,
                "payroll_category": "EMPLOYEE_TAXES",
            },
            {
                "payroll_type": "NYS_EMPLOYMENT_TAXES",
                "current": 1729,
                "payroll_category": "EMPLOYER_TAXES",
            },
            {"payroll_type": "NY_RSF", "current": 13, "payroll_category": "EMPLOYER_TAXES"},
        ]
        income = sum_payroll_components(
            components,
            payroll_types=TAX_GROUP_PAYROLL_TYPES["NYS_INCOME_TAX"],
        )
        employment = sum_payroll_components(
            components,
            payroll_types=TAX_GROUP_PAYROLL_TYPES["NYS_EMPLOYMENT_TAXES"],
        )
        self.assertEqual(income, Decimal("3595"))
        self.assertEqual(employment, Decimal("1742"))

    def test_mn_paid_leave_employee_not_in_unemployment_rollup(self):
        components = [
            {
                "payroll_type": "MN_PAID_LEAVE",
                "current": 176,
                "payroll_category": "EMPLOYEE_TAXES",
            },
            {
                "payroll_type": "MN_PAID_LEAVE_EMPLOYER",
                "current": 176,
                "payroll_category": "EMPLOYER_TAXES",
            },
        ]
        unemployment = sum_payroll_components(
            components,
            payroll_types=TAX_GROUP_PAYROLL_TYPES["MN_UNEMPLOYMENT_TAXES"],
        )
        paid_leave = sum_payroll_components(
            components, payroll_types=TAX_GROUP_PAYROLL_TYPES["MN_PAID_LEAVE"]
        )
        self.assertEqual(unemployment, Decimal("176.00"))
        self.assertEqual(paid_leave, Decimal("176.00"))

    def test_quantize_money_keeps_two_decimal_places(self):
        self.assertEqual(quantize_money(1729.2), Decimal("1729.20"))
        self.assertEqual(quantize_money("3595.02"), Decimal("3595.02"))

    def test_net_pay_from_components_matches_gross_minus_withholdings(self):
        components = [
            {"payroll_type": "Salary", "payroll_category": "PAY", "current": 50000},
            {"payroll_type": "SOCIAL_SECURITY", "payroll_category": "EMPLOYEE_TAXES", "current": 3100},
            {"payroll_type": "MEDICARE", "payroll_category": "EMPLOYEE_TAXES", "current": 725},
            {"payroll_type": "_INCOME_TAX", "payroll_category": "EMPLOYEE_TAXES", "current": 3595},
        ]
        self.assertEqual(net_pay_from_components(components), Decimal("42580.00"))

    def test_normalize_ein_strips_and_empty_to_none(self):
        self.assertIsNone(normalize_ein(""))
        self.assertIsNone(normalize_ein(None))
        self.assertEqual(normalize_ein("  12-3456789  "), "12-3456789")

    def test_federal_ein_truncates_to_fifteen_chars(self):
        long_ein = "1" * 20
        self.assertEqual(len(federal_ein_value(long_ein)), 15)
