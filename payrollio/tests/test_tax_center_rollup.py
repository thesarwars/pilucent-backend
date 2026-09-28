import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from payrollio.django_rest.helpers.tax_center_rollup import (
    _sum_federal_breakdown,
    build_federal_tax_periods,
    build_state_tax_periods,
    parse_pay_period,
    parse_report_year,
)


class TaxCenterRollupTests(unittest.TestCase):
    def test_parse_pay_period_two_digit_year(self):
        start, end = parse_pay_period("08/01/25 - 08/31/25")
        self.assertEqual(start, date(2025, 8, 1))
        self.assertEqual(end, date(2025, 8, 31))

    def test_federal_breakdown_uses_payroll_type_constants(self):
        components = [
            SimpleNamespace(payroll_type="FEDERAL_INCOME_TAX", current=Decimal("100.00")),
            SimpleNamespace(payroll_type="SOCIAL_SECURITY", current=Decimal("50.00")),
            SimpleNamespace(payroll_type="SOCIAL_SECURITY_EMPLOYER", current=Decimal("50.00")),
            SimpleNamespace(payroll_type="MEDICARE", current=Decimal("10.00")),
            SimpleNamespace(payroll_type="MEDICARE_EMPLOYER", current=Decimal("10.00")),
        ]
        breakdown = _sum_federal_breakdown(components)
        self.assertEqual(breakdown["federal_income_tax"], Decimal("100.00"))
        self.assertEqual(breakdown["total_federal_taxes"], Decimal("220.00"))

    def test_build_federal_tax_periods_without_settings(self):
        payroll = Mock()
        payroll.pay_period = "08/01/25 - 08/31/25"
        payroll.payroll_components.all.return_value = [
            SimpleNamespace(payroll_type="FEDERAL_INCOME_TAX", current=Decimal("100.00")),
            SimpleNamespace(payroll_type="SOCIAL_SECURITY", current=Decimal("50.00")),
        ]

        rows = build_federal_tax_periods([payroll], federal_tax_setting=None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tax_type"], "Federal Taxes (941/943/944)")
        self.assertEqual(rows[0]["action"], "pay")
        self.assertEqual(rows[0]["tax_breakdown"]["total_federal_taxes"], 150.0)

    def test_build_state_income_tax_row(self):
        payroll = Mock()
        payroll.pay_period = "08/14/25 - 09/05/25"
        payroll.employee.work_locations = SimpleNamespace(location_state="NY")
        payroll.payroll_components.all.return_value = [
            SimpleNamespace(payroll_type="_INCOME_TAX", current=Decimal("2856.43")),
        ]

        rows = build_state_tax_periods([payroll])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tax_type"], "NY Income Tax")
        self.assertEqual(rows[0]["tax_breakdown"]["total_state_taxes"], 2856.43)

    def test_parse_report_year_from_request(self):
        request = Mock()
        request.query_params = {"year": "2025"}
        self.assertEqual(parse_report_year(request), 2025)
