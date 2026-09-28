"""Tests for the payroll details report.

Shares the light stand-ins from the by-employee tests -- what differs here is
the row-per-run shape and the abbreviated labels, not the arithmetic.
"""

from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from payrollio.django_rest.helpers.component_labels import component_short_label
from payrollio.django_rest.helpers.payroll_details import (
    TOTAL_ROW_KEY,
    build_payroll_details,
)
from payrollio.tests.test_payroll_summary_by_employee import component, employee


def run(uid, emp, components, pay_date=date(2026, 8, 31),
        pay_period="08/01 - 08/31"):
    # `pay_date` is a real date, as the model's DateField yields -- the PDF
    # formats it with |date and a string would silently render blank.
    return SimpleNamespace(
        uid=uid,
        employee=emp,
        pay_date=pay_date,
        pay_period=pay_period,
        payroll_components=SimpleNamespace(all=lambda: components),
    )


def reference_run():
    return run(
        "run-1",
        employee("emp-1", "Abid Israk", "Ragib"),
        [
            component("Salary", "PAY", "40000.00", hours="173.33"),
            component("FEDERAL_INCOME_TAX", "EMPLOYEE_TAXES", "10927.85"),
            component("SOCIAL_SECURITY", "EMPLOYEE_TAXES", "2480.00"),
            component("MEDICARE", "EMPLOYEE_TAXES", "580.00"),
            component("NYS_INCOME_TAX", "EMPLOYEE_TAXES", "2860.02"),
            component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "0.00"),
            component("SOCIAL_SECURITY_EMPLOYER", "EMPLOYER_TAXES", "2480.00"),
            component("MEDICARE_EMPLOYER", "EMPLOYER_TAXES", "580.00"),
            component("NY_RSF", "EMPLOYER_TAXES", "0.00"),
            component("NYS_UI_EMPLOYER", "EMPLOYER_TAXES", "0.00"),
        ],
    )


def pairs(entries):
    return [(e["label"], e["amount"]) for e in entries]


class ReferenceReportTests(TestCase):
    """Reproduce the printed report the spec was taken from."""

    def setUp(self):
        self.report = build_payroll_details([reference_run()])
        self.total, self.detail = self.report["rows"]

    def test_total_row_leads(self):
        self.assertEqual(self.total["key"], TOTAL_ROW_KEY)
        self.assertTrue(self.total["is_total"])
        self.assertFalse(self.detail["is_total"])
        self.assertEqual(len(self.report["rows"]), 2)

    def test_detail_row_identifies_its_run(self):
        self.assertEqual(self.detail["pay_date"], date(2026, 8, 31))
        self.assertEqual(self.detail["pay_period"], "08/01 - 08/31")
        self.assertEqual(self.detail["name"], "Ragib, Abid Israk")
        self.assertEqual(self.detail["employee_uid"], "emp-1")

    def test_total_row_carries_no_run_identity(self):
        self.assertIsNone(self.total["pay_date"])
        self.assertEqual(self.total["name"], "")
        self.assertIsNone(self.total["employee_uid"])

    def test_gross_cell(self):
        self.assertEqual(
            pairs(self.total["cells"]["gross_pay"]),
            [
                ("Gross", "40000.00"),
                ("Salary", "40000.00"),
                ("Adjusted gross", "40000.00"),
            ],
        )

    def test_hours_ride_the_gross_cell_and_adjusted_gross_has_none(self):
        entries = self.total["cells"]["gross_pay"]
        self.assertEqual(entries[0]["hours"], "173.33")
        self.assertEqual(entries[1]["hours"], "173.33")
        # Adjusted gross is not an hours figure -- the column reads blank, not
        # 0.00h.
        self.assertIsNone(entries[2]["hours"])

    def test_employee_taxes_are_negative_and_have_no_total_line(self):
        """With no deductions, a Total line would restate the row beneath it."""
        self.assertEqual(
            pairs(self.total["cells"]["employee_taxes_deductions"]),
            [
                ("Employee taxes", "-16847.87"),
                ("Federal Income Tax", "-10927.85"),
                ("Social Security", "-2480.00"),
                ("Medicare", "-580.00"),
                ("NY Income Tax", "-2860.02"),
            ],
        )

    def test_employer_cell_is_led_by_a_total(self):
        self.assertEqual(
            pairs(self.total["cells"]["employer_taxes_contributions"]),
            [
                ("Total", "3060.00"),
                ("Employer taxes", "3060.00"),
                ("FUTA Employer", "0.00"),
                ("Social Security Employer", "2480.00"),
                ("Medicare Employer", "580.00"),
                ("NY Re-employment", "0.00"),
                ("NY SUI Employer", "0.00"),
            ],
        )

    def test_scalar_cells(self):
        self.assertEqual(self.total["cells"]["net_pay"], "23152.13")
        self.assertEqual(self.total["cells"]["total_payroll_cost"], "43060.00")

    def test_other_pay_is_empty(self):
        self.assertEqual(self.total["cells"]["other_pay"], [])

    def test_detail_rows_abbreviate_what_the_total_row_spells_out(self):
        self.assertEqual(
            pairs(self.detail["cells"]["employee_taxes_deductions"]),
            [
                ("Employee taxes", "-16847.87"),
                ("FIT", "-10927.85"),
                ("SS", "-2480.00"),
                ("Med", "-580.00"),
                ("NY IT", "-2860.02"),
            ],
        )
        self.assertEqual(
            [e["label"] for e in self.detail["cells"]["employer_taxes_contributions"]],
            ["Total", "Employer taxes", "FUTA", "SS", "Med", "NY Re-emp", "NY SUI"],
        )
        self.assertEqual(
            [e["label"] for e in self.detail["cells"]["gross_pay"]],
            ["Gross", "Sal", "Adjusted gross"],
        )

    def test_columns_are_the_printed_nine(self):
        self.assertEqual(
            [c["key"] for c in self.report["columns"]],
            [
                "pay_date",
                "name",
                "hours",
                "gross_pay",
                "other_pay",
                "employee_taxes_deductions",
                "net_pay",
                "employer_taxes_contributions",
                "total_payroll_cost",
            ],
        )


class MultipleRunTests(TestCase):
    def setUp(self):
        abid = employee("emp-1", "Abid Israk", "Ragib")
        dana = employee("emp-2", "Dana", "Abbott")
        self.report = build_payroll_details(
            [
                run("r2", abid, [component("Salary", "PAY", "1000.00", hours="40")],
                    pay_date=date(2026, 9, 30)),
                run("r1", abid, [component("Salary", "PAY", "1000.00", hours="40")],
                    pay_date=date(2026, 8, 31)),
                run("r3", dana, [component("Hourly", "PAY", "500.00", hours="20")],
                    pay_date=date(2026, 8, 31)),
            ]
        )

    def test_a_row_per_run_not_per_employee(self):
        """The summary would fold Abid's two runs into one column; this must not."""
        self.assertEqual(len(self.report["rows"]), 4)  # total + 3 runs

    def test_rows_group_by_employee_then_run_chronologically(self):
        self.assertEqual(
            [(r["name"], r["pay_date"]) for r in self.report["rows"][1:]],
            [
                ("Abbott, Dana", date(2026, 8, 31)),
                ("Ragib, Abid Israk", date(2026, 8, 31)),
                ("Ragib, Abid Israk", date(2026, 9, 30)),
            ],
        )

    def test_total_row_sums_every_run(self):
        total = self.report["rows"][0]
        self.assertEqual(total["cells"]["gross_pay"][0]["amount"], "2500.00")
        self.assertEqual(total["cells"]["gross_pay"][0]["hours"], "100.00")
        self.assertEqual(total["cells"]["net_pay"], "2500.00")

    def test_total_row_merges_pay_types_across_employees(self):
        total = self.report["rows"][0]
        self.assertEqual(
            [e["label"] for e in total["cells"]["gross_pay"]],
            ["Gross", "Hourly", "Salary", "Adjusted gross"],
        )


class DeductionTests(TestCase):
    def setUp(self):
        self.report = build_payroll_details(
            [
                run(
                    "r1",
                    employee("emp-1", "Abid Israk", "Ragib"),
                    [
                        component("Salary", "PAY", "1000.00", hours="40"),
                        component("MEDICARE", "EMPLOYEE_TAXES", "14.50"),
                        component("Health", "EMPLOYEE_DEDUCTIONS", "100.00"),
                        component("Loan On Land", "COMPANY_PAID_CONTRIBUTIONS", "50.00"),
                    ],
                )
            ],
            pretax_names={"healthinsurance"},
        )
        self.total = self.report["rows"][0]

    def test_total_line_appears_once_both_subgroups_exist(self):
        self.assertEqual(
            pairs(self.total["cells"]["employee_taxes_deductions"]),
            [
                ("Total", "-114.50"),
                ("Employee taxes", "-14.50"),
                ("Medicare", "-14.50"),
                ("Employee deductions", "-100.00"),
                ("Health", "-100.00"),
            ],
        )

    def test_contributions_join_the_employer_cell(self):
        self.assertEqual(
            pairs(self.total["cells"]["employer_taxes_contributions"]),
            [
                ("Total", "50.00"),
                ("Company contributions", "50.00"),
                ("Loan On Land", "50.00"),
            ],
        )

    def test_pretax_deduction_lowers_adjusted_gross_only(self):
        entries = self.total["cells"]["gross_pay"]
        self.assertEqual(entries[0]["amount"], "1000.00")
        self.assertEqual(entries[-1]["amount"], "900.00")

    def test_net_pay_and_total_cost(self):
        self.assertEqual(self.total["cells"]["net_pay"], "885.50")
        self.assertEqual(self.total["cells"]["total_payroll_cost"], "1050.00")


class EmptyReportTests(TestCase):
    def test_no_runs_returns_a_total_row_only(self):
        report = build_payroll_details([])
        self.assertEqual(len(report["rows"]), 1)
        total = report["rows"][0]
        self.assertEqual(total["cells"]["net_pay"], "0.00")
        self.assertEqual(total["cells"]["employee_taxes_deductions"], [])
        self.assertEqual(total["cells"]["employer_taxes_contributions"], [])
        # Gross always prints its group and adjusted lines, even at zero.
        self.assertEqual(
            pairs(total["cells"]["gross_pay"]),
            [("Gross", "0.00"), ("Adjusted gross", "0.00")],
        )


class ShortLabelTests(TestCase):
    def test_reference_abbreviations(self):
        self.assertEqual(component_short_label("FEDERAL_INCOME_TAX"), "FIT")
        self.assertEqual(component_short_label("SOCIAL_SECURITY"), "SS")
        self.assertEqual(component_short_label("SOCIAL_SECURITY_EMPLOYER"), "SS")
        self.assertEqual(component_short_label("MEDICARE_EMPLOYER"), "Med")
        self.assertEqual(component_short_label("FUTA_EMPLOYER"), "FUTA")
        self.assertEqual(component_short_label("NY_RSF"), "NY Re-emp")
        self.assertEqual(component_short_label("NYS_UI_EMPLOYER"), "NY SUI")
        self.assertEqual(component_short_label("NYS_INCOME_TAX"), "NY IT")
        self.assertEqual(component_short_label("Salary"), "Sal")

    def test_unlisted_state_follows_the_suffix_rule(self):
        self.assertEqual(component_short_label("CA_INCOME_TAX"), "CA IT")
        self.assertEqual(component_short_label("WA_UI_EMPLOYER"), "WA SUI")

    def test_unknown_codes_fall_back_to_the_full_label(self):
        """Better a long label than a clipped one."""
        self.assertEqual(component_short_label("Vision Plan"), "Vision Plan")
        self.assertEqual(
            component_short_label("MN_WORKFORCE_DEVELOPMENT_FEE"), "MN WDF"
        )
        self.assertEqual(component_short_label("SOME_NEW_TAX"), "Some New Tax")

    def test_blank(self):
        self.assertEqual(component_short_label(""), "")
        self.assertEqual(component_short_label(None), "")
