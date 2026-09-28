"""Tests for the line-level sales reports (by-customer detail, by-product
detail, by-product summary).

The assembly is tested pure against the reference PDFs' worked example (Halo
Axis, April 1 - August 4, 2026): ten transaction lines whose three printed
reports we know cell by cell. The ORM collector is tested separately for the
inclusion rules -- signing of refunds and credit memos, skipped estimates and
drafts.
"""

from datetime import date
from decimal import Decimal
from unittest import TestCase

from django.test import TestCase as DjangoTestCase

from weapi.django_rest.helpers.reports.sales_lines import (
    assemble_product_summary,
    assemble_sales_detail,
    collect_sales_lines,
    percent_string,
)


AIRPOD, GALAXY, SERVICES, BUNDLE = "p-air", "p-gal", "p-srv", "p-bun"
FRANCE, JUMATECHS = "c-fra", "c-jum"

NAMES = {
    AIRPOD: "Air Pod 3nd Gen",
    GALAXY: "Galaxy S25 Ultra 256GB",
    SERVICES: "Services",
    BUNDLE: "software bundle",
    FRANCE: "France",
    JUMATECHS: "JumaTechs",
}


def line(when, txn_type, num, customer, product, quantity, price, amount):
    return {
        "date": when,
        "txn_type": txn_type,
        "num": num,
        "txn_uid": f"t-{num}",
        "customer_uid": customer,
        "customer_name": NAMES[customer],
        "product_uid": product,
        "product_name": NAMES[product],
        "description": "",
        "quantity": Decimal(quantity),
        "sale_price": Decimal(price),
        "amount": Decimal(amount),
    }


# The Halo Axis dataset, in collect() order (date, then document number).
LINES = [
    line(date(2026, 4, 14), "Refund", "1026", JUMATECHS, AIRPOD, "-1", "500", "-500"),
    line(date(2026, 4, 14), "Invoice", "1027", FRANCE, GALAXY, "1", "1300", "1300"),
    line(date(2026, 4, 14), "Credit Memo", "1028", FRANCE, GALAXY, "-1", "1300", "-1300"),
    line(date(2026, 4, 21), "Invoice", "1029", FRANCE, AIRPOD, "40", "500", "20000"),
    line(date(2026, 6, 24), "Invoice", "1030", FRANCE, AIRPOD, "90", "500", "45000"),
    line(date(2026, 6, 24), "Invoice", "1031", JUMATECHS, GALAXY, "1", "1300", "1300"),
    line(date(2026, 6, 24), "Invoice", "1031", JUMATECHS, BUNDLE, "1", "1800", "0"),
    line(date(2026, 6, 24), "Invoice", "1031", JUMATECHS, GALAXY, "1", "1300", "1300"),
    line(date(2026, 6, 24), "Invoice", "1031", JUMATECHS, AIRPOD, "1", "500", "500"),
    line(date(2026, 6, 24), "Invoice", "1031", JUMATECHS, SERVICES, "1", "0", "0"),
]


class PercentStringTests(TestCase):
    def test_two_decimals_keep_both_when_significant(self):
        self.assertEqual(percent_string(Decimal("96.1538")), "96.15")
        self.assertEqual(percent_string(Decimal("15.3846")), "15.38")

    def test_one_trailing_zero_drops(self):
        self.assertEqual(percent_string(Decimal("20")), "20.0")
        self.assertEqual(percent_string(Decimal("100")), "100.0")
        self.assertEqual(percent_string(Decimal("0")), "0.0")


class CustomerDetailAssemblyTests(TestCase):
    def setUp(self):
        self.report = assemble_sales_detail(LINES, group_by="customer")
        self.rows = self.report["rows"]

    def test_entity_column_is_the_product(self):
        self.assertEqual(
            self.report["columns"][3],
            {
                "key": "product_name",
                "label": "Product/Service full name",
                "align": "left",
            },
        )

    def test_groups_print_alphabetically_with_their_totals(self):
        labels = [
            row["label"]
            for row in self.rows
            if row.get("is_group") or row.get("is_total")
        ]
        self.assertEqual(
            labels,
            ["France", "Total for France", "JumaTechs", "Total for JumaTechs", "TOTAL"],
        )

    def test_france_running_balance(self):
        france = [
            row
            for row in self.rows
            if row.get("depth") == 1 and row["customer_uid"] == FRANCE
        ]
        self.assertEqual(
            [row["balance"] for row in france],
            ["1300.00", "0.00", "20000.00", "65000.00"],
        )

    def test_jumatechs_running_balance_restarts(self):
        juma = [
            row
            for row in self.rows
            if row.get("depth") == 1 and row["customer_uid"] == JUMATECHS
        ]
        self.assertEqual(
            [row["balance"] for row in juma],
            ["-500.00", "800.00", "800.00", "2100.00", "2600.00", "2600.00"],
        )

    def test_group_totals_carry_quantity_and_amount(self):
        totals = {row["key"]: row for row in self.rows if row.get("is_total")}
        self.assertEqual(totals[f"{FRANCE}.total"]["quantity"], "130.00")
        self.assertEqual(totals[f"{FRANCE}.total"]["amount"], "65000.00")
        self.assertEqual(totals[f"{JUMATECHS}.total"]["quantity"], "4.00")
        self.assertEqual(totals[f"{JUMATECHS}.total"]["amount"], "2600.00")

    def test_grand_total(self):
        total = self.rows[-1]
        self.assertEqual(total["key"], "total")
        self.assertEqual(total["quantity"], "134.00")
        self.assertEqual(total["amount"], "67600.00")

    def test_negative_lines_keep_a_positive_unit_price(self):
        refund = next(row for row in self.rows if row.get("txn_type") == "Refund")
        self.assertEqual(refund["quantity"], "-1.00")
        self.assertEqual(refund["sale_price"], "500.00")
        self.assertEqual(refund["amount"], "-500.00")


class ProductDetailAssemblyTests(TestCase):
    def setUp(self):
        self.report = assemble_sales_detail(LINES, group_by="product")
        self.rows = self.report["rows"]

    def test_entity_column_is_the_customer(self):
        self.assertEqual(
            self.report["columns"][3],
            {"key": "customer_name", "label": "Customer full name", "align": "left"},
        )

    def test_groups_sort_case_insensitively(self):
        groups = [row["label"] for row in self.rows if row.get("is_group")]
        self.assertEqual(
            groups,
            [
                "Air Pod 3nd Gen",
                "Galaxy S25 Ultra 256GB",
                "Services",
                "software bundle",
            ],
        )

    def test_airpod_running_balance(self):
        airpod = [
            row
            for row in self.rows
            if row.get("depth") == 1 and row["product_uid"] == AIRPOD
        ]
        self.assertEqual(
            [row["balance"] for row in airpod],
            ["-500.00", "19500.00", "64500.00", "65000.00"],
        )

    def test_galaxy_nets_to_two_units(self):
        totals = {row["key"]: row for row in self.rows if row.get("is_total")}
        self.assertEqual(totals[f"{GALAXY}.total"]["quantity"], "2.00")
        self.assertEqual(totals[f"{GALAXY}.total"]["amount"], "2600.00")

    def test_grand_total_matches_the_customer_grouping(self):
        total = self.rows[-1]
        self.assertEqual(total["quantity"], "134.00")
        self.assertEqual(total["amount"], "67600.00")


class ProductSummaryAssemblyTests(TestCase):
    def setUp(self):
        self.report = assemble_product_summary(
            LINES, {AIRPOD: Decimal("400"), GALAXY: Decimal("1100")}
        )
        self.by_key = {row["key"]: row for row in self.report["rows"]}

    def test_airpod_row(self):
        row = self.by_key[AIRPOD]
        self.assertEqual(row["quantity"], "130.00")
        self.assertEqual(row["amount"], "65000.00")
        self.assertEqual(row["pct_of_sales"], "96.15")
        self.assertEqual(row["avg_price"], "500.00")
        self.assertEqual(row["cogs"], "52000.00")
        self.assertEqual(row["avg_cogs"], "400.00")
        self.assertEqual(row["gross_margin"], "13000.00")
        self.assertEqual(row["gross_margin_pct"], "20.0")

    def test_galaxy_row_prices_the_net_quantity(self):
        row = self.by_key[GALAXY]
        self.assertEqual(row["quantity"], "2.00")
        self.assertEqual(row["pct_of_sales"], "3.85")
        self.assertEqual(row["cogs"], "2200.00")
        self.assertEqual(row["avg_cogs"], "1100.00")
        self.assertEqual(row["gross_margin"], "400.00")
        self.assertEqual(row["gross_margin_pct"], "15.38")

    def test_zero_sales_rows_leave_margin_blank(self):
        for key in (SERVICES, BUNDLE):
            row = self.by_key[key]
            self.assertEqual(row["amount"], "0.00")
            self.assertEqual(row["pct_of_sales"], "0.0")
            self.assertEqual(row["cogs"], "0.00")
            self.assertIsNone(row["gross_margin"])
            self.assertIsNone(row["gross_margin_pct"])

    def test_total_row(self):
        row = self.by_key["total"]
        self.assertEqual(row["quantity"], "134.00")
        self.assertEqual(row["amount"], "67600.00")
        self.assertEqual(row["pct_of_sales"], "100.0")
        self.assertEqual(row["avg_price"], "504.48")
        self.assertEqual(row["cogs"], "54200.00")
        self.assertEqual(row["avg_cogs"], "404.48")
        # The reference prints the TOTAL's margin cells empty.
        self.assertIsNone(row["gross_margin"])
        self.assertIsNone(row["gross_margin_pct"])


class CollectSalesLinesTests(DjangoTestCase):
    """Inclusion rules: what counts, what is skipped, how rows are signed."""

    @classmethod
    def setUpTestData(cls):
        from companyio.models import Company
        from creditnoteio.choices import CreditNoteKindChoices
        from creditnoteio.models import CreditNote, CreditNoteItem
        from customerio.models import Customer
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        from salesio.choices import SaleReceptKindChoices, SalesStatusChoices
        from salesio.models import Sale, SaleItem

        cls.company = Company.objects.create(name="Halo Axis")
        cls.customer = Customer.objects.create(
            company=cls.company, first_name="Juma", display_name="JumaTechs"
        )
        cls.product = Product.objects.create(
            company=cls.company,
            title="Air Pod 3nd Gen",
            sku="AP3",
            quantity=500,
            date=date(2026, 1, 1),
            kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE,
        )

        def sale(invoice_id, when, **overrides):
            fields = {
                "company": cls.company,
                "customer": cls.customer,
                "invoice_id": invoice_id,
                "date": when,
                "status": SalesStatusChoices.OPEN,
                "is_invoice": True,
            }
            fields.update(overrides)
            return Sale.objects.create(**fields)

        invoice = sale("2001", date(2026, 6, 24))
        SaleItem.objects.create(
            sale=invoice,
            product=cls.product,
            quantity=2,
            sale_price=Decimal("500"),
            total=Decimal("1000"),
        )

        refund = sale(
            "2002",
            date(2026, 6, 25),
            is_invoice=False,
            is_sale_receipt=True,
            kind=SaleReceptKindChoices.REFUND,
        )
        SaleItem.objects.create(
            sale=refund,
            product=cls.product,
            quantity=1,
            sale_price=Decimal("500"),
            total=Decimal("500"),
        )

        # Estimates and drafts never reach the report.
        estimate = sale("2003", date(2026, 6, 26), is_invoice=False, is_estimated=True)
        SaleItem.objects.create(sale=estimate, product=cls.product, quantity=9)
        draft = sale("2004", date(2026, 6, 26), status=SalesStatusChoices.DRAFT)
        SaleItem.objects.create(sale=draft, product=cls.product, quantity=9)

        note = CreditNote.objects.create(
            company=cls.company,
            customer=cls.customer,
            credit_note_number="3001",
            date=date(2026, 6, 27),
            kind=CreditNoteKindChoices.SALE,
        )
        CreditNoteItem.objects.create(
            credit_note=note,
            product=cls.product,
            quantity=1,
            item_credit=Decimal("500"),
            total=Decimal("500"),
        )

    def test_rows_types_and_signs(self):
        rows = collect_sales_lines(self.company)
        self.assertEqual(
            [(r["txn_type"], r["num"], r["quantity"], r["amount"]) for r in rows],
            [
                ("Invoice", "2001", Decimal("2"), Decimal("1000.00")),
                ("Refund", "2002", Decimal("-1"), Decimal("-500.00")),
                ("Credit Memo", "3001", Decimal("-1"), Decimal("-500.00")),
            ],
        )

    def test_rows_carry_both_entity_labels(self):
        row = collect_sales_lines(self.company)[0]
        self.assertEqual(row["customer_name"], "JumaTechs")
        self.assertEqual(row["product_name"], "Air Pod 3nd Gen")
        self.assertEqual(row["customer_uid"], str(self.customer.uid))
        self.assertEqual(row["product_uid"], str(self.product.uid))

    def test_date_range_bounds_are_inclusive(self):
        rows = collect_sales_lines(
            self.company, date_from=date(2026, 6, 25), date_to=date(2026, 6, 27)
        )
        self.assertEqual([r["num"] for r in rows], ["2002", "3001"])
