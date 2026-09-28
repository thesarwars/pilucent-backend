"""DB-backed tests: seed, rule versioning, aggregation, and recompute."""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from addressio.choices import AddressConnectorKindCoices
from addressio.models import Address, AddressConnector
from companyio.models import Company
from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNote, CreditNoteItem
from customerio.models import Customer
from salesio.choices import SalesStatusChoices, SaleReceptKindChoices
from salesio.models import Sale, SaleItem

from nexusio.choices import NexusStatusChoices
from nexusio.models import NexusStateRule, NexusStateStatus
from nexusio.services.aggregation import aggregate_by_state_month, sum_window
from nexusio.services.recompute import recompute_company
from nexusio.services.rules import rule_in_force, rules_in_force


class SeedAndRuleTests(TestCase):
    def test_seed_is_idempotent_and_versions_kentucky(self):
        call_command("seed_nexus_state_rules")
        self.assertEqual(NexusStateRule.objects.count(), 53)  # 52 juris + KY 2nd row
        self.assertEqual(NexusStateRule.objects.filter(state_code="KY").count(), 2)

        # Re-run: no duplicates.
        call_command("seed_nexus_state_rules")
        self.assertEqual(NexusStateRule.objects.count(), 53)

    def test_kentucky_rule_in_force_flips_on_change_date(self):
        call_command("seed_nexus_state_rules")
        before = rule_in_force("KY", date(2026, 7, 15))
        after = rule_in_force("KY", date(2026, 8, 15))
        self.assertEqual(before.combination_logic, "OR")
        self.assertEqual(before.txn_threshold, 200)
        self.assertEqual(after.combination_logic, "SALES_ONLY")
        self.assertIsNone(after.txn_threshold)

    def test_rules_in_force_one_per_state(self):
        call_command("seed_nexus_state_rules")
        rules = rules_in_force(date(2026, 8, 15))
        self.assertEqual(len(rules), 52)  # one per jurisdiction
        self.assertEqual(rules["KY"].combination_logic, "SALES_ONLY")
        self.assertEqual(rules["NY"].combination_logic, "AND")


class AggregationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")

    def _customer(self, province, country="us"):
        cust = Customer.objects.create(first_name="C", company=self.company)
        addr = Address.objects.create(
            company=self.company, province=province, country=country
        )
        AddressConnector.objects.create(
            kind=AddressConnectorKindCoices.CUSTOMER, customer=cust, address=addr
        )
        return cust

    def _sale(self, customer, when, lines, *, kind=SaleReceptKindChoices.SALE):
        sale = Sale.objects.create(
            invoice_id=f"INV-{Sale.objects.count()+1}",
            customer=customer,
            company=self.company,
            date=when,
            is_invoice=True,
            kind=kind,
            status=SalesStatusChoices.PAID,
        )
        for total, is_tax in lines:
            SaleItem.objects.create(
                sale=sale, total=Decimal(total), is_tax=is_tax
            )
        return sale

    def test_state_attribution_and_taxable_split(self):
        ca = self._customer("California")
        self._sale(ca, date(2026, 3, 1), [("60000", True), ("40000", False)])
        buckets, unattributed = aggregate_by_state_month(self.company)
        b = buckets["CA"][date(2026, 3, 1)]
        self.assertEqual(b["gross"], Decimal("100000"))
        self.assertEqual(b["taxable"], Decimal("60000"))
        self.assertEqual(len(b["sales"]), 1)  # two lines, one transaction
        self.assertEqual(unattributed["gross"], Decimal("0"))

    def test_refund_and_credit_note_net_down(self):
        ny = self._customer("NY")
        self._sale(ny, date(2026, 2, 1), [("100000", True)])
        self._sale(ny, date(2026, 2, 10), [("30000", True)], kind=SaleReceptKindChoices.REFUND)
        cn = CreditNote.objects.create(
            credit_note_number="CN-1", kind=CreditNoteKindChoices.SALE,
            company=self.company, customer=ny, date=date(2026, 2, 20),
            status=CreditNoteStatusChoices.OPEN,  # issued (not draft)
        )
        CreditNoteItem.objects.create(credit_note=cn, total=Decimal("20000"))
        buckets, _ = aggregate_by_state_month(self.company)
        window = sum_window(buckets["NY"], date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(window["gross"], Decimal("50000"))  # 100k - 30k - 20k
        self.assertEqual(window["count"], 1)  # only the positive invoice counts

    def test_unattributed_bucket_for_missing_state(self):
        foreign = self._customer("Ontario", country="ca")
        no_addr = Customer.objects.create(first_name="N", company=self.company)
        self._sale(foreign, date(2026, 4, 1), [("70000", True)])
        self._sale(no_addr, date(2026, 4, 1), [("5000", True)])
        buckets, unattributed = aggregate_by_state_month(self.company)
        self.assertNotIn("CA", buckets)
        self.assertEqual(unattributed["gross"], Decimal("75000"))


class RecomputeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        call_command("seed_nexus_state_rules")

    def _sell(self, province, total, when=date(2026, 6, 1), is_tax=True):
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
        SaleItem.objects.create(sale=sale, total=Decimal(total), is_tax=is_tax)

    def test_recompute_marks_met_and_stamps_immutable_date(self):
        # $120k into California ($500k sales-only? no -> CA is $500k). Use a $100k
        # state: sell $120k into Arizona ($100k sales-only).
        self._sell("AZ", "120000")
        recompute_company(self.company, today=date(2026, 6, 15))
        az = NexusStateStatus.objects.get(company=self.company, state_code="AZ")
        self.assertTrue(az.threshold_met)
        self.assertEqual(az.status, NexusStatusChoices.MET)
        self.assertEqual(az.threshold_met_date, date(2026, 6, 15))
        self.assertEqual(az.sales_amount, Decimal("120000.00"))

        # Re-run on a later date: met-date stays the first crossing (immutable).
        recompute_company(self.company, today=date(2026, 9, 20))
        az.refresh_from_db()
        self.assertEqual(az.threshold_met_date, date(2026, 6, 15))

    def test_no_sales_tax_state_is_not_applicable(self):
        recompute_company(self.company, today=date(2026, 6, 15))
        oregon = NexusStateStatus.objects.get(company=self.company, state_code="OR")
        self.assertEqual(oregon.status, NexusStatusChoices.NOT_APPLICABLE)
        self.assertFalse(oregon.threshold_met)

    def test_new_york_and_guard_no_nexus_on_transaction_count(self):
        # 150 tiny NY invoices = $15k: >100 txns but far under $500k -> NOT met.
        for _ in range(150):
            self._sell("NY", "100")
        recompute_company(self.company, today=date(2026, 6, 15))
        ny = NexusStateStatus.objects.get(company=self.company, state_code="NY")
        self.assertFalse(ny.threshold_met)
        self.assertEqual(ny.txn_count, 150)

    def test_recompute_covers_all_states(self):
        recompute_company(self.company, today=date(2026, 6, 15))
        self.assertEqual(
            NexusStateStatus.objects.filter(company=self.company).count(), 52
        )

    def test_current_or_previous_year_evaluates_each_year_separately(self):
        # NJ ($100k, CURRENT_OR_PREVIOUS_YEAR): $70k in 2025 + $70k in 2026-to-date.
        # Neither calendar year crosses $100k, so NO nexus — the two years must NOT
        # be summed into $140k (the false-positive the review caught).
        self._sell("NJ", "70000", when=date(2025, 5, 1))
        self._sell("NJ", "70000", when=date(2026, 5, 1))
        recompute_company(self.company, today=date(2026, 7, 7))
        nj = NexusStateStatus.objects.get(company=self.company, state_code="NJ")
        self.assertFalse(nj.threshold_met)
        self.assertEqual(nj.status, NexusStatusChoices.NOT_APPROACHING)
        # Governing window shows a single year's $70k (70%), not $140k.
        self.assertEqual(nj.sales_amount, Decimal("70000.00"))
        self.assertEqual(nj.pct_of_sales_threshold, Decimal("0.7000"))

    def test_previous_year_crossing_alone_triggers_nexus(self):
        # $120k into NJ in the prior year alone -> met (previous-year window).
        self._sell("NJ", "120000", when=date(2025, 8, 1))
        recompute_company(self.company, today=date(2026, 7, 7))
        nj = NexusStateStatus.objects.get(company=self.company, state_code="NJ")
        self.assertTrue(nj.threshold_met)
        self.assertEqual(nj.sales_amount, Decimal("120000.00"))

    def test_puerto_rico_sales_attribute(self):
        self._sell("Puerto Rico", "150000", when=date(2026, 5, 1))
        result = recompute_company(self.company, today=date(2026, 7, 7))
        pr = NexusStateStatus.objects.get(company=self.company, state_code="PR")
        self.assertTrue(pr.threshold_met)  # $150k >= $100k
        self.assertEqual(result["unattributed"]["gross"], Decimal("0"))

    def test_draft_credit_note_does_not_net_down(self):
        from creditnoteio.choices import CreditNoteStatusChoices

        self._sell("NJ", "105000", when=date(2026, 5, 1))
        # A DRAFT sales credit memo must NOT reduce the measured sales.
        cust = Customer.objects.filter(company=self.company).first()
        cn = CreditNote.objects.create(
            credit_note_number="CN-D", kind=CreditNoteKindChoices.SALE,
            company=self.company, customer=cust, date=date(2026, 5, 10),
            status=CreditNoteStatusChoices.DRAFT,
        )
        CreditNoteItem.objects.create(credit_note=cn, total=Decimal("10000"))
        recompute_company(self.company, today=date(2026, 7, 7))
        nj = NexusStateStatus.objects.get(company=self.company, state_code="NJ")
        self.assertTrue(nj.threshold_met)  # 105k stands; draft credit ignored
        self.assertEqual(nj.sales_amount, Decimal("105000.00"))
