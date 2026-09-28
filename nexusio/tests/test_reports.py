"""Tests for the three Economic Nexus report builders."""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from addressio.choices import AddressConnectorKindCoices
from addressio.models import Address, AddressConnector
from companyio.models import Company
from customerio.models import Customer
from salesio.choices import SalesStatusChoices, SaleReceptKindChoices
from salesio.models import Sale, SaleItem

from nexusio.choices import NexusStatusChoices
from nexusio.models import NexusStateStatus
from nexusio.services.recompute import recompute_company

from weapi.django_rest.helpers.reports.nexus_reports import (
    nexus_approaching_risk,
    nexus_exposure,
    nexus_threshold_history,
)


class NexusReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        call_command("seed_nexus_state_rules")

    def _sell(self, province, total):
        cust = Customer.objects.create(first_name="C", company=self.company)
        addr = Address.objects.create(company=self.company, province=province, country="us")
        AddressConnector.objects.create(
            kind=AddressConnectorKindCoices.CUSTOMER, customer=cust, address=addr
        )
        sale = Sale.objects.create(
            invoice_id=f"INV-{Sale.objects.count()+1}", customer=cust,
            company=self.company, date=date(2026, 5, 1), is_invoice=True,
            kind=SaleReceptKindChoices.SALE, status=SalesStatusChoices.PAID,
        )
        SaleItem.objects.create(sale=sale, total=Decimal(total), is_tax=True)

    def test_exposure_lists_all_states_with_totals(self):
        self._sell("AZ", "120000")  # met
        self._sell("CO", "85000")   # approaching ($100k)
        recompute_company(self.company, today=date(2026, 6, 1))

        report = nexus_exposure(self.company)
        self.assertEqual(len(report["rows"]), 52)
        self.assertEqual(report["total"]["met"], 1)
        self.assertEqual(report["total"]["approaching"], 1)
        # sorted: MET/APPROACHING rise above NOT_APPROACHING
        self.assertEqual(report["rows"][0]["state_code"], "AZ")

    def test_approaching_risk_only_approaching_sorted_by_pct(self):
        self._sell("AZ", "120000")  # met (excluded)
        self._sell("CO", "85000")   # 85%
        self._sell("GA", "95000")   # 95%
        recompute_company(self.company, today=date(2026, 6, 1))

        report = nexus_approaching_risk(self.company)
        codes = [r["state_code"] for r in report["rows"]]
        self.assertEqual(codes, ["GA", "CO"])  # highest % first, AZ (met) excluded
        self.assertEqual(report["total"]["count"], 2)

    def test_approaching_risk_ranks_by_transaction_pct_when_higher(self):
        # A state approaching via the transaction test (95%) but with low sales
        # (10%) must outrank a state approaching via sales (82%): "closest first"
        # ranks by whichever of the two percentages is nearer to 100%.
        NexusStateStatus.objects.create(
            company=self.company, state_code="GA", status=NexusStatusChoices.APPROACHING,
            pct_of_sales_threshold=Decimal("0.1000"),
            pct_of_txn_threshold=Decimal("0.9500"),
        )
        NexusStateStatus.objects.create(
            company=self.company, state_code="CO", status=NexusStatusChoices.APPROACHING,
            pct_of_sales_threshold=Decimal("0.8200"),
            pct_of_txn_threshold=Decimal("0.0000"),
        )
        report = nexus_approaching_risk(self.company)
        self.assertEqual([r["state_code"] for r in report["rows"]], ["GA", "CO"])

    def test_threshold_history_lists_alerts(self):
        self._sell("AZ", "120000")  # crosses -> CROSSED alert
        recompute_company(self.company, today=date(2026, 6, 1))
        report = nexus_threshold_history(self.company)
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["state_code"], "AZ")
        self.assertEqual(report["rows"][0]["alert_type"], "CROSSED")
        self.assertEqual(report["total"]["crossed"], 1)
