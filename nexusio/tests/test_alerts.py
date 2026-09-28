"""Tests for nexus alert emission, episode de-dup, and delivery."""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from addressio.choices import AddressConnectorKindCoices
from addressio.models import Address, AddressConnector
from companyio.models import Company, CompanyUser
from customerio.models import Customer
from salesio.choices import SalesStatusChoices, SaleReceptKindChoices
from salesio.models import Sale, SaleItem

from nexusio.choices import NexusAlertTypeChoices
from nexusio.models import NexusAlertLog
from nexusio.services import registration as reg_service
from nexusio.services.recompute import recompute_company

from notificationio.models import Notification


class AlertTests(TestCase):
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

    def test_crossing_emits_one_alert_and_is_idempotent(self):
        self._sell("AZ", "120000")  # AZ $100k -> crossed
        recompute_company(self.company, today=date(2026, 6, 1))
        alerts = NexusAlertLog.objects.filter(company=self.company, state_code="AZ")
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts.first().alert_type, NexusAlertTypeChoices.CROSSED)

        # Re-run: no duplicate (same episode).
        recompute_company(self.company, today=date(2026, 6, 5))
        self.assertEqual(
            NexusAlertLog.objects.filter(company=self.company, state_code="AZ").count(), 1
        )

    def test_approaching_emits_alert(self):
        self._sell("AZ", "85000")  # 85% of $100k
        recompute_company(self.company, today=date(2026, 6, 1))
        alert = NexusAlertLog.objects.get(company=self.company, state_code="AZ")
        self.assertEqual(alert.alert_type, NexusAlertTypeChoices.APPROACHING)

    def test_registered_state_does_not_emit_crossing_alert(self):
        self._sell("AZ", "120000")
        reg_service.mark_physical_nexus(self.company, "AZ")
        recompute_company(self.company, today=date(2026, 6, 1))
        self.assertFalse(
            NexusAlertLog.objects.filter(company=self.company, state_code="AZ").exists()
        )

    def test_approach_then_cross_is_two_alerts_one_each(self):
        self._sell("AZ", "85000")  # approaching
        recompute_company(self.company, today=date(2026, 6, 1))
        self._sell("AZ", "40000")  # now 125k -> crossed
        recompute_company(self.company, today=date(2026, 6, 2))
        types = set(
            NexusAlertLog.objects.filter(
                company=self.company, state_code="AZ"
            ).values_list("alert_type", flat=True)
        )
        self.assertEqual(types, {"APPROACHING", "CROSSED"})

    def test_notification_delivered_to_company_users(self):
        user = User.objects.create(email="owner@acme.test", password="x")
        CompanyUser.objects.create(company=self.company, user=user)
        self._sell("AZ", "120000")
        recompute_company(self.company, today=date(2026, 6, 1))
        note = Notification.objects.filter(
            user=user, kind="NEXUS_THRESHOLD_CROSSED"
        ).first()
        self.assertIsNotNone(note)
        self.assertEqual(note.model_kind, "NEXUS")
        self.assertTrue(note.is_company)

    def test_unregistering_a_crossed_state_fires_the_crossed_alert(self):
        # Crosses while REGISTERED -> alert suppressed (threshold_met stored True).
        self._sell("AZ", "120000")
        reg_service.mark_physical_nexus(self.company, "AZ")
        recompute_company(self.company, today=date(2026, 6, 1))
        self.assertFalse(
            NexusAlertLog.objects.filter(company=self.company, state_code="AZ").exists()
        )
        # Removing the registration makes it an actionable MET obligation: the
        # CROSSED alert must fire now even though threshold_met was already True.
        reg_service.remove_registration(self.company, "AZ")
        recompute_company(self.company, today=date(2026, 6, 2))
        alert = NexusAlertLog.objects.get(company=self.company, state_code="AZ")
        self.assertEqual(alert.alert_type, NexusAlertTypeChoices.CROSSED)

    def test_acknowledge(self):
        from django.utils import timezone

        self._sell("AZ", "120000")
        recompute_company(self.company, today=date(2026, 6, 1))
        alert = NexusAlertLog.objects.get(company=self.company, state_code="AZ")
        self.assertIsNone(alert.acknowledged_at)
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=["acknowledged_at"])
        alert.refresh_from_db()
        self.assertIsNotNone(alert.acknowledged_at)
