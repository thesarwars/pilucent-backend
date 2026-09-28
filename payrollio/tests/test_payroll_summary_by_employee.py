"""Tests for the by-employee payroll summary pivot.

The grid builder takes any object exposing `employee` and `payroll_components`,
so these drive it with light stand-ins rather than a full company/RLS fixture --
what is under test is the pivot arithmetic and row ordering, not the ORM.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from payrollio.django_rest.helpers.component_labels import component_label
from payrollio.django_rest.helpers.payroll_summary_by_employee import (
    TOTAL_COLUMN_KEY,
    build_payroll_summary_by_employee,
)


def component(payroll_type, category, current, hours=0):
    return SimpleNamespace(
        payroll_type=payroll_type,
        payroll_category=category,
        current=Decimal(str(current)),
        hours=Decimal(str(hours)),
    )


def employee(uid, first_name, last_name, middle_name=None):
    return SimpleNamespace(
        uid=uid,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        user=SimpleNamespace(name=f"{first_name} {last_name}"),
    )


def payroll(emp, components):
    return SimpleNamespace(
        employee=emp,
        payroll_components=SimpleNamespace(all=lambda: components),
    )


def row_map(grid):
    """Flatten every section into {row key: row} for assertions."""
    return {
        row["key"]: row
        for section in grid["sections"]
        for row in section["rows"]
    }


# The figures from the reference report, for one salaried employee.
def reference_payroll():
    return payroll(
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


class ReferenceReportTests(TestCase):
    """Reproduce the printed report the spec was taken from, figure for figure."""

    def setUp(self):
        self.grid = build_payroll_summary_by_employee([reference_payroll()])
        self.rows = row_map(self.grid)

    def test_total_column_comes_first(self):
        self.assertEqual(self.grid["columns"][0]["key"], TOTAL_COLUMN_KEY)
        self.assertEqual(self.grid["columns"][0]["label"], "Total")
        self.assertTrue(self.grid["columns"][0]["is_total"])

    def test_employee_column_is_last_comma_first(self):
        self.assertEqual(self.grid["columns"][1]["label"], "Ragib, Abid Israk")
        self.assertEqual(self.grid["columns"][1]["employee_uid"], "emp-1")

    def test_hours(self):
        self.assertEqual(self.rows["hours"]["values"]["emp-1"], "173.33")
        self.assertEqual(self.rows["hours"]["format"], "hours")
        self.assertEqual(self.rows["hours.Salary"]["values"]["emp-1"], "173.33")

    def test_gross_and_adjusted_gross(self):
        self.assertEqual(self.rows["gross"]["values"]["emp-1"], "40000.00")
        self.assertEqual(self.rows["gross.Salary"]["values"]["emp-1"], "40000.00")
        # No pre-tax deductions, so adjusted gross equals gross.
        self.assertEqual(self.rows["adjusted_gross"]["values"]["emp-1"], "40000.00")

    def test_other_pay_is_an_empty_row(self):
        self.assertTrue(self.rows["other_pay"]["is_empty"])

    def test_employee_taxes_are_negative(self):
        self.assertEqual(
            self.rows["employee_taxes_deductions"]["values"]["emp-1"], "-16847.87"
        )
        self.assertEqual(self.rows["employee_taxes"]["values"]["emp-1"], "-16847.87")
        self.assertEqual(
            self.rows["employee_taxes.FEDERAL_INCOME_TAX"]["values"]["emp-1"],
            "-10927.85",
        )
        self.assertEqual(
            self.rows["employee_taxes.NYS_INCOME_TAX"]["values"]["emp-1"], "-2860.02"
        )

    def test_net_pay(self):
        self.assertEqual(self.rows["net_pay"]["values"]["emp-1"], "23152.13")

    def test_employer_costs_stay_positive(self):
        self.assertEqual(
            self.rows["employer_taxes_contributions"]["values"]["emp-1"], "3060.00"
        )
        self.assertEqual(
            self.rows["employer_taxes.SOCIAL_SECURITY_EMPLOYER"]["values"]["emp-1"],
            "2480.00",
        )
        # A tax that did not apply still prints, so columns stay comparable.
        self.assertEqual(
            self.rows["employer_taxes.FUTA_EMPLOYER"]["values"]["emp-1"], "0.00"
        )

    def test_total_payroll_cost(self):
        self.assertEqual(self.rows["total_payroll_cost"]["values"]["emp-1"], "43060.00")

    def test_federal_lines_sort_above_state_lines(self):
        keys = [
            row["key"]
            for section in self.grid["sections"]
            if section["key"] == "employer_taxes_contributions"
            for row in section["rows"]
        ]
        self.assertEqual(
            keys,
            [
                "employer_taxes_contributions",
                "employer_taxes",
                "employer_taxes.FUTA_EMPLOYER",
                "employer_taxes.SOCIAL_SECURITY_EMPLOYER",
                "employer_taxes.MEDICARE_EMPLOYER",
                # Sorted by label -- "NY Re-employment" then "NY SUI Employer",
                # which is the reverse of their raw code order.
                "employer_taxes.NY_RSF",
                "employer_taxes.NYS_UI_EMPLOYER",
            ],
        )

    def test_labels_match_the_printed_report(self):
        labels = {row["key"]: row["label"] for row in row_map(self.grid).values()}
        self.assertEqual(
            labels["employee_taxes.FEDERAL_INCOME_TAX"], "Federal Income Tax"
        )
        self.assertEqual(labels["employee_taxes.NYS_INCOME_TAX"], "NY Income Tax")
        self.assertEqual(labels["employer_taxes.NY_RSF"], "NY Re-employment")
        self.assertEqual(labels["employer_taxes.NYS_UI_EMPLOYER"], "NY SUI Employer")
        self.assertEqual(labels["employer_taxes.FUTA_EMPLOYER"], "FUTA Employer")


class MultipleEmployeeTests(TestCase):
    def setUp(self):
        self.grid = build_payroll_summary_by_employee(
            [
                payroll(
                    employee("emp-1", "Abid Israk", "Ragib"),
                    [
                        component("Salary", "PAY", "1000.00", hours="40"),
                        component("MEDICARE", "EMPLOYEE_TAXES", "14.50"),
                    ],
                ),
                payroll(
                    employee("emp-2", "Dana", "Abbott"),
                    [
                        component("Hourly", "PAY", "500.00", hours="20"),
                        component("SOCIAL_SECURITY", "EMPLOYEE_TAXES", "31.00"),
                    ],
                ),
            ]
        )
        self.rows = row_map(self.grid)

    def test_columns_sort_by_display_name(self):
        self.assertEqual(
            [column["label"] for column in self.grid["columns"]],
            ["Total", "Abbott, Dana", "Ragib, Abid Israk"],
        )

    def test_total_column_sums_every_employee(self):
        self.assertEqual(self.rows["gross"]["values"][TOTAL_COLUMN_KEY], "1500.00")
        self.assertEqual(self.rows["hours"]["values"][TOTAL_COLUMN_KEY], "60.00")
        self.assertEqual(self.rows["net_pay"]["values"][TOTAL_COLUMN_KEY], "1454.50")

    def test_every_row_spans_every_column(self):
        """A line one employee lacks prints 0.00 rather than leaving a gap."""
        column_keys = {column["key"] for column in self.grid["columns"]}
        for row in self.rows.values():
            self.assertEqual(set(row["values"]), column_keys, row["key"])
        self.assertEqual(self.rows["employee_taxes.MEDICARE"]["values"]["emp-2"], "0.00")
        self.assertEqual(
            self.rows["employee_taxes.SOCIAL_SECURITY"]["values"]["emp-1"], "0.00"
        )

    def test_pay_types_from_both_employees_appear(self):
        self.assertIn("gross.Salary", self.rows)
        self.assertIn("gross.Hourly", self.rows)


class MultipleRunsTests(TestCase):
    def test_runs_accumulate_into_one_column(self):
        emp = employee("emp-1", "Abid Israk", "Ragib")
        grid = build_payroll_summary_by_employee(
            [
                payroll(emp, [component("Salary", "PAY", "1000.00", hours="40")]),
                payroll(emp, [component("Salary", "PAY", "1000.00", hours="40")]),
            ]
        )
        rows = row_map(grid)
        self.assertEqual(len(grid["columns"]), 2)
        self.assertEqual(rows["gross"]["values"]["emp-1"], "2000.00")
        self.assertEqual(rows["hours"]["values"]["emp-1"], "80.00")


class DeductionTests(TestCase):
    def build(self, pretax_names=frozenset()):
        return row_map(
            build_payroll_summary_by_employee(
                [
                    payroll(
                        employee("emp-1", "Abid Israk", "Ragib"),
                        [
                            component("Salary", "PAY", "1000.00", hours="40"),
                            component("Health", "EMPLOYEE_DEDUCTIONS", "100.00"),
                            component(
                                "Loan On Land", "COMPANY_PAID_CONTRIBUTIONS", "50.00"
                            ),
                        ],
                    )
                ],
                pretax_names=pretax_names,
            )
        )

    def test_deductions_join_the_withheld_section(self):
        rows = self.build()
        self.assertEqual(rows["employee_deductions"]["values"]["emp-1"], "-100.00")
        self.assertEqual(
            rows["employee_deductions.Health"]["values"]["emp-1"], "-100.00"
        )
        self.assertEqual(
            rows["employee_taxes_deductions"]["values"]["emp-1"], "-100.00"
        )
        self.assertEqual(rows["net_pay"]["values"]["emp-1"], "900.00")

    def test_contributions_join_the_employer_section(self):
        rows = self.build()
        self.assertEqual(
            rows["employer_contributions.Loan On Land"]["values"]["emp-1"], "50.00"
        )
        self.assertEqual(rows["total_payroll_cost"]["values"]["emp-1"], "1050.00")

    def test_unmatched_deduction_leaves_adjusted_gross_at_gross(self):
        """The safe direction: never subtract a deduction we cannot prove pre-tax."""
        rows = self.build()
        self.assertEqual(rows["adjusted_gross"]["values"]["emp-1"], "1000.00")

    def test_matched_pretax_deduction_lowers_adjusted_gross(self):
        rows = self.build(pretax_names={"health"})
        self.assertEqual(rows["adjusted_gross"]["values"]["emp-1"], "900.00")
        self.assertEqual(rows["gross"]["values"]["emp-1"], "1000.00")

    def test_component_name_matches_a_longer_setup_name(self):
        """Production pairs a `Health` component with a `Health Insurance` setup."""
        rows = self.build(pretax_names={"healthinsurance"})
        self.assertEqual(rows["adjusted_gross"]["values"]["emp-1"], "900.00")

    def test_short_names_do_not_match_on_substring(self):
        """`HSA` must not match every setup name containing those letters."""
        rows = row_map(
            build_payroll_summary_by_employee(
                [
                    payroll(
                        employee("emp-1", "Abid Israk", "Ragib"),
                        [
                            component("Salary", "PAY", "1000.00", hours="40"),
                            component("HSA", "EMPLOYEE_DEDUCTIONS", "100.00"),
                        ],
                    )
                ],
                pretax_names={"taxablehsaplan"},
            )
        )
        self.assertEqual(rows["adjusted_gross"]["values"]["emp-1"], "1000.00")


class EmptyReportTests(TestCase):
    def test_no_payrolls_still_returns_the_skeleton(self):
        grid = build_payroll_summary_by_employee([])
        rows = row_map(grid)
        self.assertEqual([c["key"] for c in grid["columns"]], [TOTAL_COLUMN_KEY])
        self.assertEqual(rows["gross"]["values"][TOTAL_COLUMN_KEY], "0.00")
        self.assertEqual(rows["net_pay"]["values"][TOTAL_COLUMN_KEY], "0.00")
        # Tax sub-rows are driven by the data, so an empty report has none.
        self.assertNotIn("employee_taxes", rows)


class ComponentLabelTests(TestCase):
    def test_explicit_codes(self):
        self.assertEqual(component_label("FEDERAL_INCOME_TAX"), "Federal Income Tax")
        self.assertEqual(component_label("MEDICARE_EMPLOYER"), "Medicare Employer")
        self.assertEqual(component_label("MN_UI_EMPLOYER"), "MN UI Employer")

    def test_state_prefix_stays_upper_case(self):
        self.assertEqual(component_label("CA_INCOME_TAX"), "CA Income Tax")

    def test_acronyms_survive_title_casing(self):
        self.assertEqual(component_label("WA_SUI_EMPLOYER"), "WA SUI Employer")

    def test_free_text_deduction_names_pass_through(self):
        self.assertEqual(component_label("Vision Plan"), "Vision Plan")
        self.assertEqual(component_label("Salary"), "Salary")

    def test_missing_state_prefix_does_not_print_an_underscore(self):
        """Production has rows where the state prefix never resolved."""
        self.assertEqual(component_label("_INCOME_TAX"), "State Income Tax")

    def test_blank(self):
        self.assertEqual(component_label(""), "")
        self.assertEqual(component_label(None), "")
