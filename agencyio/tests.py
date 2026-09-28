"""Tests for Agency.get_sale_overview — the data behind the Sales-tax hero cards."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import ChartOfAccount
from companyio.models import Company
from customerio.models import Customer
from salesio.choices import SalesStatusChoices, SaleReceptKindChoices
from salesio.models import Sale, SaleItem

from agencyio.choices import (
    AgencyFillingFrequencyChoices,
    AgencyReportingMethod,
    AgencyStatusChoices,
)
from agencyio.models import Agency, AgencyTax, AgencyTaxSet


class SaleOverviewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Acme")
        self.agency = Agency.objects.create(
            company=self.company,
            title="Minnesota DOR",
            filling_frequency=AgencyFillingFrequencyChoices.MONTHLY,
            reporting_method=AgencyReportingMethod.ACCRUAL,
            status=AgencyStatusChoices.ACTIVE,
            state="MN",
        )
        self.tax = AgencyTax.objects.create(company=self.company, total_rate=8.0)
        coa = ChartOfAccount.objects.create(company=self.company, code="2200")
        AgencyTaxSet.objects.create(
            agency=self.agency, taxes=self.tax, rate=Decimal("0.080"),
            sales_tax_account=coa,
        )
        self.customer = Customer.objects.create(first_name="C", company=self.company)
        self._inv = 0

    def _sale(self, when, total_tax, items):
        """One sale on `when`; items = list of (total, is_tax)."""
        self._inv += 1
        sale = Sale.objects.create(
            invoice_id=f"INV-{self._inv}", company=self.company, customer=self.customer,
            date=when, status=SalesStatusChoices.PAID, kind=SaleReceptKindChoices.SALE,
            total_tax=Decimal(total_tax),
        )
        for total, is_tax in items:
            SaleItem.objects.create(
                sale=sale, tax=self.tax, is_tax=is_tax, total=Decimal(total)
            )
        return sale

    def test_accrual_overview_period_scoped_with_tax_and_rate(self):
        # In May: $1000 taxable + $200 non-taxable, $80 tax collected.
        self._sale(date(2026, 5, 10), "80.000", [("1000.000", True), ("200.000", False)])
        # Out of period (April) — must be excluded entirely.
        self._sale(date(2026, 4, 10), "999.000", [("9000.000", True)])

        ov = self.agency.get_sale_overview(today=date(2026, 5, 15))

        self.assertEqual(ov["total_taxable_sale"], Decimal("1000"))
        self.assertEqual(ov["total_non_taxable_sale"], Decimal("200"))
        self.assertEqual(ov["total_gross_sale"], Decimal("1200"))
        # reconciles
        self.assertEqual(
            ov["total_gross_sale"],
            ov["total_taxable_sale"] + ov["total_non_taxable_sale"],
        )
        self.assertEqual(ov["tax_owed"], Decimal("80.00"))
        self.assertEqual(ov["combined_rate"], Decimal("0.08"))

    def test_multi_taxed_line_sale_does_not_double_count_tax(self):
        # One sale, two agency-taxed lines, $50 total tax. tax_owed must be 50, not 100.
        self._sale(date(2026, 5, 3), "50.000", [("500.000", True), ("500.000", True)])

        ov = self.agency.get_sale_overview(today=date(2026, 5, 15))

        self.assertEqual(ov["total_taxable_sale"], Decimal("1000"))
        self.assertEqual(ov["tax_owed"], Decimal("50.00"))
        self.assertEqual(ov["combined_rate"], Decimal("0.05"))

    def test_no_sales_returns_zeros_and_zero_rate(self):
        ov = self.agency.get_sale_overview(today=date(2026, 5, 15))
        self.assertEqual(ov["total_taxable_sale"], Decimal("0"))
        self.assertEqual(ov["total_gross_sale"], Decimal("0"))
        self.assertEqual(ov["tax_owed"], Decimal("0"))
        self.assertEqual(ov["combined_rate"], Decimal("0"))

    def test_quarterly_period_bounds_follow_fiscal_start(self):
        self.agency.filling_frequency = AgencyFillingFrequencyChoices.QUARTERLY
        self.agency.start_of_period = "January"
        self.agency.save()
        start, end = self.agency.current_period_bounds(today=date(2026, 5, 15))
        self.assertEqual((start, end), (date(2026, 4, 1), date(2026, 6, 30)))
