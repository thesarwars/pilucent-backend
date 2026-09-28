"""Tests for the pure A/P Aging Detail assembler.

Reconciles against the worked example in
``docs/updated-prompts/AP_Aging_Detail_Report_Documentation.md`` (section 11),
aged as of 2026-06-24. No DB needed -- ``assemble_report`` is ORM-free.
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from weapi.django_rest.helpers.reports.ap_aging_detail import (
    assemble_report,
    credit_amounts,
    _bucket_key,
)

AS_OF = date(2026, 6, 24)


def _bill(name, amount, open_balance, due):
    return {
        "uid": name,
        "kind": "BILL",
        "transaction_type": "Bill",
        "date": due,
        "num": f"#PUR-{name}",
        "vendor_display_name": name,
        "store_full_name": "",
        "due_date": due,
        "past_due": max(0, (AS_OF - due).days),
        "amount": Decimal(amount),
        "open_balance": Decimal(open_balance),
        "_aging_date": due,
        "_has_due_date": True,
    }


def _credit(name, total, remaining, when):
    return {
        "uid": name,
        "kind": "VENDOR_CREDIT",
        "transaction_type": "Vendor Credit",
        "date": when,
        "num": "",
        "vendor_display_name": name,
        "store_full_name": "",
        "due_date": None,
        "past_due": None,
        "amount": -Decimal(total),
        "open_balance": -Decimal(remaining),
        "_aging_date": when,
        "_has_due_date": False,
    }


def _sample_rows():
    return [
        _bill("Binary Burst", "12000.00", "12000.00", date(2025, 5, 26)),
        _bill("Unimart", "400000.00", "400000.00", date(2025, 7, 10)),
        _bill("Kaniz", "1200.00", "1200.00", date(2026, 4, 14)),
        _credit("Unimart", "1360.00", "210.00", date(2025, 4, 23)),
        _credit("Kaniz", "400.00", "400.00", date(2025, 6, 16)),
        _credit("Binary Burst", "2250.00", "2250.00", date(2025, 6, 16)),
        _credit("Ragib", "4100.00", "4100.00", date(2025, 6, 16)),
        _credit("Binary Burst", "400.00", "400.00", date(2025, 6, 25)),
        _credit("Ragib", "1000.00", "1000.00", date(2025, 6, 25)),
        _credit("Unimart", "4000.00", "4000.00", date(2025, 6, 25)),
    ]


class ApAgingDetailAssemblerTests(SimpleTestCase):
    def setUp(self):
        self.report = assemble_report(_sample_rows(), AS_OF)

    def test_only_nonempty_bands_in_most_overdue_first_order(self):
        keys = [b["key"] for b in self.report["bands"]]
        self.assertEqual(keys, ["90_plus", "61_90"])  # empty bands omitted

    def test_band_labels_and_counts(self):
        b90, b61 = self.report["bands"]
        self.assertEqual(b90["label"], "91 or more days past due")
        self.assertEqual(b90["count"], 9)  # 2 bills + 7 credits
        self.assertEqual(b61["label"], "61 - 90 days past due")
        self.assertEqual(b61["count"], 1)

    def test_band_subtotals_match_doc(self):
        b90, b61 = self.report["bands"]
        # 412,000 bills − 13,510 credit totals
        self.assertEqual(b90["subtotal"]["amount"], 398490.00)
        # 412,000 bills − 12,360 credit open balances
        self.assertEqual(b90["subtotal"]["open_balance"], 399640.00)
        self.assertEqual(b61["subtotal"]["amount"], 1200.00)
        self.assertEqual(b61["subtotal"]["open_balance"], 1200.00)

    def test_grand_total_matches_doc(self):
        self.assertEqual(self.report["total"]["amount"], 399690.00)
        self.assertEqual(self.report["total"]["open_balance"], 400840.00)

    def test_amount_open_gap_is_applied_credit(self):
        # Section 11.3: the 1,150 gap is the applied part of the Unimart credit.
        total = self.report["total"]
        self.assertEqual(total["open_balance"] - total["amount"], 1150.00)

    def test_within_band_sort_bills_before_credits(self):
        rows = self.report["bands"][0]["rows"]  # 90_plus
        kinds = [r["kind"] for r in rows]
        # All bills come before all vendor credits.
        self.assertEqual(kinds, ["BILL", "BILL"] + ["VENDOR_CREDIT"] * 7)
        # Bills are ordered oldest due date first.
        self.assertEqual(rows[0]["due_date"], "2025-05-26")
        self.assertEqual(rows[1]["due_date"], "2025-07-10")


class CreditAmountsTests(SimpleTestCase):
    """The vendor-credit Amount/Open balance derivation (doc section 11).

    The apply flow decrements the stored CreditNote.total AND records a
    used_total, so stored total == remaining and original == total + applied.
    """

    def test_partially_applied_credit_matches_doc_unimart(self):
        # Unimart: original 1,360 with 1,150 applied -> stored total 210.
        amount, open_balance = credit_amounts(Decimal("210.00"), Decimal("1150.00"))
        self.assertEqual(amount, Decimal("-1360.00"))  # original, doc Amount
        self.assertEqual(open_balance, Decimal("-210.00"))  # remaining, doc Open

    def test_unapplied_credit_amount_equals_open_balance(self):
        amount, open_balance = credit_amounts(Decimal("400.00"), Decimal("0"))
        self.assertEqual(amount, Decimal("-400.00"))
        self.assertEqual(open_balance, Decimal("-400.00"))


class ApAgingSummaryAssemblerTests(SimpleTestCase):
    """Reconciles the A/P Aging Summary worked example (Halo Axis, doc section 10),
    aged as of 2026-06-24. Same underlying dataset as the Detail example."""

    @staticmethod
    def _row(vendor_uid, vendor_name, open_balance, aging):
        return {
            "vendor_uid": vendor_uid,
            "vendor_display_name": vendor_name,
            "open_balance": Decimal(open_balance),
            "_aging_date": aging,
        }

    def setUp(self):
        from weapi.django_rest.helpers.reports.ap_aging_summary import (
            assemble_summary,
        )

        rows = [
            # Binary Burst -> all 91+, nets to 9,350
            self._row("bb", "Binary Burst", "12000.00", date(2025, 5, 26)),
            self._row("bb", "Binary Burst", "-2250.00", date(2025, 6, 16)),
            self._row("bb", "Binary Burst", "-400.00", date(2025, 6, 25)),
            # Kaniz -> 1,200 in 61-90, -400 in 91+, total 800
            self._row("kz", "Kaniz", "1200.00", date(2026, 4, 14)),
            self._row("kz", "Kaniz", "-400.00", date(2025, 6, 16)),
            # Ragib -> -5,100 in 91+
            self._row("rg", "Ragib", "-4100.00", date(2025, 6, 16)),
            self._row("rg", "Ragib", "-1000.00", date(2025, 6, 25)),
            # Unimart -> 395,790 in 91+
            self._row("um", "Unimart", "400000.00", date(2025, 7, 10)),
            self._row("um", "Unimart", "-210.00", date(2025, 4, 23)),
            self._row("um", "Unimart", "-4000.00", date(2025, 6, 25)),
        ]
        self.report = assemble_summary(rows, AS_OF)

    def test_rows_sorted_alphabetically_one_per_vendor(self):
        names = [r["vendor_display_name"] for r in self.report["rows"]]
        self.assertEqual(names, ["Binary Burst", "Kaniz", "Ragib", "Unimart"])

    def test_vendor_rows_match_doc(self):
        by_name = {r["vendor_display_name"]: r for r in self.report["rows"]}
        self.assertEqual(by_name["Binary Burst"]["buckets"]["90_plus"], 9350.00)
        self.assertEqual(by_name["Binary Burst"]["total"], 9350.00)
        self.assertEqual(by_name["Kaniz"]["buckets"]["61_90"], 1200.00)
        self.assertEqual(by_name["Kaniz"]["buckets"]["90_plus"], -400.00)
        self.assertEqual(by_name["Kaniz"]["total"], 800.00)
        self.assertEqual(by_name["Ragib"]["total"], -5100.00)
        self.assertEqual(by_name["Unimart"]["buckets"]["90_plus"], 395790.00)
        self.assertEqual(by_name["Unimart"]["total"], 395790.00)

    def test_column_totals_match_doc(self):
        cols = self.report["column_totals"]
        self.assertEqual(cols["61_90"], 1200.00)
        self.assertEqual(cols["90_plus"], 399640.00)
        self.assertEqual(cols["current"], 0.0)
        self.assertEqual(cols["1_30"], 0.0)
        self.assertEqual(cols["31_60"], 0.0)

    def test_grand_total_and_cross_check(self):
        # Grand total reachable across columns and down vendor totals (doc 6.4).
        self.assertEqual(self.report["total"], 400840.00)
        across = sum(self.report["column_totals"].values())
        down = sum(r["total"] for r in self.report["rows"])
        self.assertEqual(round(across, 2), 400840.00)
        self.assertEqual(round(down, 2), 400840.00)


class ApAgingSummaryEdgeCaseTests(SimpleTestCase):
    @staticmethod
    def _row(uid, name, open_balance, aging):
        return {
            "vendor_uid": uid,
            "vendor_display_name": name,
            "open_balance": Decimal(open_balance),
            "_aging_date": aging,
        }

    def _build(self, rows):
        from weapi.django_rest.helpers.reports.ap_aging_summary import (
            assemble_summary,
        )

        return assemble_summary(rows, AS_OF)

    def test_all_zero_buckets_vendor_is_suppressed(self):
        # +100 and -100 in the SAME bucket -> every cell nets to 0 -> hidden.
        report = self._build(
            [
                self._row("z", "Zeromart", "100.00", date(2025, 1, 1)),
                self._row("z", "Zeromart", "-100.00", date(2025, 1, 2)),
            ]
        )
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["total"], 0.0)

    def test_net_zero_total_but_nonzero_cells_is_kept(self):
        # +100 in 61-90 and -100 in 91+ -> total 0 but the cells carry detail.
        report = self._build(
            [
                self._row("k", "Keepme", "100.00", date(2026, 4, 14)),
                self._row("k", "Keepme", "-100.00", date(2025, 1, 2)),
            ]
        )
        self.assertEqual(len(report["rows"]), 1)
        row = report["rows"][0]
        self.assertEqual(row["total"], 0.0)
        self.assertEqual(row["buckets"]["61_90"], 100.0)
        self.assertEqual(row["buckets"]["90_plus"], -100.0)

    def test_same_name_distinct_vendors_order_by_uid(self):
        report = self._build(
            [
                self._row("b", "Acme", "5.00", date(2025, 1, 1)),
                self._row("a", "Acme", "5.00", date(2025, 1, 1)),
            ]
        )
        self.assertEqual([r["vendor_uid"] for r in report["rows"]], ["a", "b"])


AR_AS_OF = date(2026, 6, 24)


class ArAgingDetailAssemblerTests(SimpleTestCase):
    """Reconciles the A/R Aging Detail worked example (Halo Axis, doc section 11):
    two Net-30 invoices dated 06/24/2026, due 07/24/2026 -> both Current."""

    @staticmethod
    def _invoice(name, amount, open_balance, due):
        return {
            "uid": name,
            "kind": "INVOICE",
            "transaction_type": "Invoice",
            "date": due,
            "num": "1030",
            "customer_display_name": name,
            "store_full_name": "",
            "due_date": due,
            "past_due": max(0, (AR_AS_OF - due).days),
            "amount": Decimal(amount),
            "open_balance": Decimal(open_balance),
            "_aging_date": due,
            "_has_due_date": True,
        }

    @staticmethod
    def _credit(name, amount, open_balance, when):
        return {
            "uid": name,
            "kind": "CREDIT_MEMO",
            "transaction_type": "Credit Memo",
            "date": when,
            "num": "",
            "customer_display_name": name,
            "store_full_name": "",
            "due_date": None,
            "past_due": None,
            "amount": Decimal(amount),
            "open_balance": Decimal(open_balance),
            "_aging_date": when,
            "_has_due_date": False,
        }

    def _build(self, rows):
        from weapi.django_rest.helpers.reports.ap_aging_detail import assemble_report
        from weapi.django_rest.helpers.reports.ar_aging_detail import _public_row

        return assemble_report(rows, AR_AS_OF, public_row=_public_row)

    def test_sample_two_invoices_all_current(self):
        report = self._build(
            [
                self._invoice("France", "49331.25", "49331.25", date(2026, 7, 24)),
                self._invoice("JumaTechs", "3330.75", "3330.75", date(2026, 7, 24)),
            ]
        )
        self.assertEqual([b["key"] for b in report["bands"]], ["current"])
        band = report["bands"][0]
        self.assertEqual(band["label"], "Current")
        self.assertEqual(band["count"], 2)
        self.assertEqual(band["subtotal"]["amount"], 52662.00)
        self.assertEqual(band["subtotal"]["open_balance"], 52662.00)
        self.assertEqual(report["total"]["amount"], 52662.00)
        self.assertEqual(report["total"]["open_balance"], 52662.00)
        # rows carry customer_display_name (not vendor_display_name)
        self.assertIn("customer_display_name", band["rows"][0])

    def test_credit_memo_is_negative_and_ages_by_its_date(self):
        # Invoice (Current) + a partially-applied credit memo (original 300,
        # 100 applied -> open -200), dated long ago -> 91+ band.
        report = self._build(
            [
                self._invoice("Acme", "1000.00", "1000.00", date(2026, 7, 24)),
                self._credit("Acme", "-300.00", "-200.00", date(2025, 1, 1)),
            ]
        )
        bands = {b["key"]: b for b in report["bands"]}
        self.assertEqual(set(bands), {"90_plus", "current"})
        self.assertEqual(bands["90_plus"]["subtotal"]["amount"], -300.00)
        self.assertEqual(bands["90_plus"]["subtotal"]["open_balance"], -200.00)
        self.assertEqual(bands["current"]["subtotal"]["amount"], 1000.00)
        # Grand total nets invoice against credit memo (doc 6.4)
        self.assertEqual(report["total"]["amount"], 700.00)
        self.assertEqual(report["total"]["open_balance"], 800.00)


class ArAgingSummaryAssemblerTests(SimpleTestCase):
    """Reconciles the A/R Aging Summary worked example (Halo Axis, doc section 10):
    two current invoices -> one current row each, grand total 52,662.00."""

    @staticmethod
    def _row(uid, name, open_balance, aging):
        return {
            "customer_uid": uid,
            "customer_display_name": name,
            "open_balance": Decimal(open_balance),
            "_aging_date": aging,
        }

    def _build(self, rows):
        from weapi.django_rest.helpers.reports.ap_aging_summary import (
            assemble_summary,
        )

        return assemble_summary(rows, AR_AS_OF, party="customer")

    def setUp(self):
        self.report = self._build(
            [
                self._row("fr", "France", "49331.25", date(2026, 7, 24)),
                self._row("jt", "JumaTechs", "3330.75", date(2026, 7, 24)),
            ]
        )

    def test_one_current_row_per_customer_with_customer_keys(self):
        names = [r["customer_display_name"] for r in self.report["rows"]]
        self.assertEqual(names, ["France", "JumaTechs"])
        # Output uses customer_* keys (party='customer'), not vendor_*.
        self.assertIn("customer_uid", self.report["rows"][0])
        self.assertNotIn("vendor_uid", self.report["rows"][0])

    def test_customer_rows_and_columns_match_doc(self):
        by_name = {r["customer_display_name"]: r for r in self.report["rows"]}
        self.assertEqual(by_name["France"]["buckets"]["current"], 49331.25)
        self.assertEqual(by_name["France"]["total"], 49331.25)
        self.assertEqual(by_name["JumaTechs"]["buckets"]["current"], 3330.75)
        self.assertEqual(self.report["column_totals"]["current"], 52662.00)
        self.assertEqual(self.report["column_totals"]["90_plus"], 0.0)

    def test_grand_total_and_cross_check(self):
        self.assertEqual(self.report["total"], 52662.00)
        across = sum(self.report["column_totals"].values())
        down = sum(r["total"] for r in self.report["rows"])
        self.assertEqual(round(across, 2), 52662.00)
        self.assertEqual(round(down, 2), 52662.00)


class InventoryValuationSummaryTests(SimpleTestCase):
    """Reconciles the Inventory Valuation Summary worked example (Halo Axis,
    doc section 10): AirPods 572 @ 228,950 and Galaxy 99 @ 99,000."""

    def _build(self, items):
        from weapi.django_rest.helpers.reports.inventory_valuation_summary import (
            assemble_valuation,
        )

        return assemble_valuation(items, AR_AS_OF)

    def test_worked_example_rows_and_totals(self):
        report = self._build(
            [
                {"uid": "a", "product": "Air Pod 3nd Gen", "sku": "",
                 "quantity": 572, "asset_value": Decimal("228950.00")},
                {"uid": "g", "product": "Galaxy S25 Ultra 256GB", "sku": "",
                 "quantity": 99, "asset_value": Decimal("99000.00")},
            ]
        )
        by = {r["product"]: r for r in report["rows"]}
        self.assertEqual(by["Air Pod 3nd Gen"]["asset_value"], 228950.00)
        self.assertEqual(by["Air Pod 3nd Gen"]["calc_avg"], 400.26)  # 228950/572
        self.assertEqual(by["Galaxy S25 Ultra 256GB"]["calc_avg"], 1000.00)
        self.assertEqual(report["total"]["quantity"], 671.00)
        self.assertEqual(report["total"]["asset_value"], 327950.00)
        self.assertEqual(report["total"]["calc_avg"], 488.75)  # weighted

    def test_total_calc_avg_is_weighted_not_mean_of_means(self):
        report = self._build(
            [
                {"uid": "a", "product": "A", "sku": "", "quantity": 572,
                 "asset_value": Decimal("228950.00")},
                {"uid": "g", "product": "G", "sku": "", "quantity": 99,
                 "asset_value": Decimal("99000.00")},
            ]
        )
        self.assertEqual(report["total"]["calc_avg"], 488.75)
        self.assertNotEqual(report["total"]["calc_avg"], round((400.26 + 1000.00) / 2, 2))

    def test_zero_quantity_yields_zero_calc_avg_no_division_error(self):
        report = self._build(
            [{"uid": "z", "product": "New", "sku": "NS1", "quantity": 0,
              "asset_value": Decimal("0.00")}]
        )
        self.assertEqual(report["rows"][0]["calc_avg"], 0.0)
        self.assertEqual(report["total"]["calc_avg"], 0.0)
        self.assertEqual(report["total"]["asset_value"], 0.0)


class TaxableSalesSummaryTests(SimpleTestCase):
    """Reconciles the Taxable Sales Summary worked example (Halo Axis, doc 10):
    no-item -20, Air Pod 3nd Gen 65,500, Gadget>Air Pod 2nd Gen (deleted) 100,
    Galaxy 26,000 -> grand total 91,580.00."""

    def _build(self, buckets, has_no_item):
        from weapi.django_rest.helpers.reports.taxable_sales_summary import (
            assemble_taxable_sales,
        )

        return assemble_taxable_sales(buckets, AR_AS_OF, has_no_item=has_no_item)

    def setUp(self):
        self.report = self._build(
            [
                {"key": None, "label": "", "category": None, "amount": Decimal("-20.00")},
                {"key": "ap3", "label": "Air Pod 3nd Gen", "category": None,
                 "amount": Decimal("65500.00")},
                {"key": "ap2", "label": "Air Pod 2nd Gen (deleted)", "category": "Gadget",
                 "amount": Decimal("100.00")},
                {"key": "gal", "label": "Galaxy S25 Ultra 256GB", "category": None,
                 "amount": Decimal("26000.00")},
            ],
            has_no_item=True,
        )

    def test_no_item_bucket_and_grand_total(self):
        self.assertEqual(self.report["no_item"]["amount"], -20.00)
        self.assertEqual(self.report["total"], 91580.00)

    def test_uncategorized_items_sorted(self):
        labels = [r["label"] for r in self.report["items"]]
        self.assertEqual(labels, ["Air Pod 3nd Gen", "Galaxy S25 Ultra 256GB"])

    def test_category_subtotal_with_deleted_item(self):
        self.assertEqual(len(self.report["categories"]), 1)
        gadget = self.report["categories"][0]
        self.assertEqual(gadget["label"], "Gadget")
        self.assertEqual(gadget["amount"], 100.00)
        self.assertEqual(gadget["items"][0]["label"], "Air Pod 2nd Gen (deleted)")

    def test_no_item_absent_when_flag_false(self):
        report = self._build(
            [{"key": "x", "label": "X", "category": None, "amount": Decimal("5.00")}],
            has_no_item=False,
        )
        self.assertIsNone(report["no_item"])
        self.assertEqual(report["total"], 5.00)


class SalesTaxLiabilityTests(SimpleTestCase):
    """Reconciles the Sales Tax Liability worked example (Halo Axis, doc 11):
    NY agency $2,186.37 + CA agency $4,331.25; agency total sums Tax only."""

    def _build(self, rows):
        from weapi.django_rest.helpers.reports.sales_tax_liability import (
            assemble_liability,
        )

        return assemble_liability(rows, AR_AS_OF)

    def setUp(self):
        def row(agency_uid, agency, name, gross, non_taxable, taxable, tax):
            return {
                "agency_uid": agency_uid, "agency": agency, "name": name,
                "gross": Decimal(gross), "non_taxable": Decimal(non_taxable),
                "taxable": Decimal(taxable), "tax": Decimal(tax),
            }

        NY = "New York Department of Taxation and Finance"
        CA = "California Department of Tax and Fee Administration"
        self.report = self._build(
            [
                row("ny", NY, "New York State", "2600", "500", "2100", "83.99"),
                row("ny", NY, "New York, New York City", "2600", "500", "2100", "102.38"),
                row("ny", NY, "Sales Tax", "20000", "0", "20000", "2000.00"),
                row("ca", CA, "California State", "45000", "0", "45000", "2812.50"),
                row("ca", CA, "California, San Mateo County", "45000", "0", "45000", "450.00"),
                row("ca", CA, "California, San Mateo City District", "45000", "0", "45000", "112.50"),
                row("ca", CA, "California, San Mateo County District", "45000", "0", "45000", "956.25"),
            ]
        )
        self.by_uid = {a["agency_uid"]: a for a in self.report["agencies"]}

    def test_agency_totals_sum_tax_only(self):
        self.assertEqual(self.by_uid["ny"]["tax_total"], 2186.37)
        self.assertEqual(self.by_uid["ca"]["tax_total"], 4331.25)

    def test_period_grand_total(self):
        self.assertEqual(self.report["total"], 6517.62)

    def test_component_rows_carry_base_but_agency_total_has_no_gross(self):
        ny = self.by_uid["ny"]
        # component rows keep gross/taxable...
        self.assertEqual(ny["rows"][0]["taxable_amount"], 2100.00)
        self.assertEqual(ny["rows"][2]["tax_amount"], 2000.00)
        # ...but the agency object exposes only the Tax total (no gross/taxable sum)
        self.assertNotIn("gross_total", ny)
        self.assertNotIn("taxable_amount", ny)


class BucketLadderTests(SimpleTestCase):
    def test_boundaries(self):
        cases = {
            0: "current",
            -5: "current",
            1: "1_30",
            30: "1_30",
            31: "31_60",
            60: "31_60",
            61: "61_90",
            90: "61_90",
            91: "90_plus",
            394: "90_plus",
        }
        for days, expected in cases.items():
            aging_date = AS_OF - __import__("datetime").timedelta(days=days)
            self.assertEqual(_bucket_key(aging_date, AS_OF), expected, days)

    def test_no_aging_date_is_current(self):
        self.assertEqual(_bucket_key(None, AS_OF), "current")
