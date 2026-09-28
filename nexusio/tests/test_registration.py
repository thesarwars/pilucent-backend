"""Tests for the P2 agency handoff: registration, settings, status flip."""

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

from nexusio.choices import (
    NexusRegistrationStatusChoices,
    NexusRegistrationTypeChoices,
    NexusStatusChoices,
)
from nexusio.models import NexusAgencyRegistration, NexusSettings, NexusStateStatus
from nexusio.services import registration as reg_service
from nexusio.services.recompute import recompute_company


class RegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        call_command("seed_nexus_state_rules")

    def _sell(self, province, total, when=date(2026, 5, 1)):
        cust = Customer.objects.create(first_name="C", company=self.company)
        addr = Address.objects.create(company=self.company, province=province, country="us")
        AddressConnector.objects.create(
            kind=AddressConnectorKindCoices.CUSTOMER, customer=cust, address=addr
        )
        sale = Sale.objects.create(
            invoice_id=f"INV-{Sale.objects.count()+1}", customer=cust,
            company=self.company, date=when, is_invoice=True,
            kind=SaleReceptKindChoices.SALE, status=SalesStatusChoices.PAID,
        )
        SaleItem.objects.create(sale=sale, total=Decimal(total), is_tax=True)

    def test_mark_physical_nexus_shows_registered_after_recompute(self):
        recompute_company(self.company, today=date(2026, 6, 1))  # FL starts NOT_APPROACHING
        reg = reg_service.mark_physical_nexus(self.company, "FL")
        self.assertEqual(reg.registration_type, NexusRegistrationTypeChoices.PHYSICAL_MANUAL)
        self.assertEqual(reg.registration_status, NexusRegistrationStatusChoices.REGISTERED)
        self.assertIn("FL", reg_service.registered_state_codes(self.company))
        # The status row reflects it after a recompute (the view triggers this).
        recompute_company(self.company, today=date(2026, 6, 1))
        fl = NexusStateStatus.objects.get(company=self.company, state_code="FL")
        self.assertEqual(fl.status, NexusStatusChoices.REGISTERED)

    def test_no_sales_tax_state_stays_not_applicable_even_with_registration(self):
        # Defensive: even if a registration exists for a NONE state, recompute
        # keeps it NOT_APPLICABLE (the endpoints also reject marking such states).
        reg_service.mark_physical_nexus(self.company, "OR")  # Oregon: no sales tax
        recompute_company(self.company, today=date(2026, 6, 1))
        oregon = NexusStateStatus.objects.get(company=self.company, state_code="OR")
        self.assertEqual(oregon.status, NexusStatusChoices.NOT_APPLICABLE)

    def test_registered_wins_over_met_on_recompute(self):
        self._sell("AZ", "120000")  # AZ $100k -> would be MET
        reg_service.mark_physical_nexus(self.company, "AZ")
        recompute_company(self.company, today=date(2026, 6, 1))
        az = NexusStateStatus.objects.get(company=self.company, state_code="AZ")
        self.assertTrue(az.threshold_met)  # numerically met...
        self.assertEqual(az.status, NexusStatusChoices.REGISTERED)  # ...but registered wins

    def test_start_agency_setup_records_intent(self):
        reg = reg_service.start_agency_setup(
            self.company, "AZ", collection_start_date=date(2026, 6, 1),
            filing_frequency="QUARTERLY",
        )
        self.assertEqual(reg.registration_type, NexusRegistrationTypeChoices.ECONOMIC)
        self.assertEqual(reg.registration_status, NexusRegistrationStatusChoices.NOT_STARTED)
        self.assertEqual(reg.filing_frequency, "QUARTERLY")
        self.assertNotIn("AZ", reg_service.registered_state_codes(self.company))

        # Completing it registers the state.
        reg2 = reg_service.start_agency_setup(self.company, "AZ", mark_registered=True)
        self.assertEqual(reg2.registration_status, NexusRegistrationStatusChoices.REGISTERED)
        self.assertIn("AZ", reg_service.registered_state_codes(self.company))

    def test_remove_registration_restores_numeric_status(self):
        self._sell("AZ", "120000")
        reg_service.mark_physical_nexus(self.company, "AZ")
        recompute_company(self.company, today=date(2026, 6, 1))
        self.assertEqual(
            NexusStateStatus.objects.get(company=self.company, state_code="AZ").status,
            NexusStatusChoices.REGISTERED,
        )
        reg_service.remove_registration(self.company, "AZ")
        recompute_company(self.company, today=date(2026, 6, 1))
        az = NexusStateStatus.objects.get(company=self.company, state_code="AZ")
        self.assertEqual(az.status, NexusStatusChoices.MET)  # back to the numeric verdict

    def test_settings_warning_fraction_changes_approaching(self):
        self._sell("AZ", "60000")  # 60% of AZ $100k
        recompute_company(self.company, today=date(2026, 6, 1))
        az = NexusStateStatus.objects.get(company=self.company, state_code="AZ")
        self.assertEqual(az.status, NexusStatusChoices.NOT_APPROACHING)  # 60% < default 80%

        settings = NexusSettings.objects.create(
            company=self.company, warning_fraction=Decimal("0.500")
        )
        self.assertEqual(settings.warning_fraction, Decimal("0.500"))
        recompute_company(self.company, today=date(2026, 6, 1))
        az.refresh_from_db()
        self.assertEqual(az.status, NexusStatusChoices.APPROACHING)  # 60% >= 50%
