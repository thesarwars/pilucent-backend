"""Tests for the tax-and-wage summary and the total payroll cost reports."""

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from payrollio.django_rest.helpers.payroll_tax_wage_summary import (
    build_tax_and_wage_summary,
    resolve_wage_base,
)
from payrollio.django_rest.helpers.payroll_total_cost import (
    build_total_payroll_cost,
)
from payrollio.tests.test_payroll_summary_by_employee import component


def payroll(components, employee_id=1):
    return SimpleNamespace(
        employee_id=employee_id,
        payroll_components=SimpleNamespace(all=lambda: components),
    )


def reference_components():
    return [
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
    ]


NY_CONFIG = {"uiWageBase": 12800}


def rows_of(report):
    return [
        (
            r["label"],
            r["total_wages"],
            r["excess_wages"],
            r["taxable_wages"],
            r["tax_amount"],
        )
        for r in report["rows"]
    ]


class ReferenceReportTests(TestCase):
    """The reference employee has already passed the FUTA and NY UI bases."""

    def setUp(self):
        self.report = build_tax_and_wage_summary(
            [payroll(reference_components())],
            state_code="NY",
            year=2026,
            # 40k earned earlier in the year: past FUTA's 7,000 and NY UI's
            # 12,800, but nowhere near Social Security's 184,500.
            prior_wages={1: Decimal("40000.00")},
            state_config=NY_CONFIG,
        )

    def test_matches_the_reference_line_for_line(self):
        self.assertEqual(
            rows_of(self.report),
            [
                ("Federal Taxes (941/943/944)", None, None, None, "17047.85"),
                ("Federal Income Tax", "40000.00", "0.00", "40000.00", "10927.85"),
                ("Social Security", "40000.00", "0.00", "40000.00", "2480.00"),
                ("Social Security Employer", "40000.00", "0.00", "40000.00",
                 "2480.00"),
                ("Medicare", "40000.00", "0.00", "40000.00", "580.00"),
                ("Medicare Employer", "40000.00", "0.00", "40000.00", "580.00"),
                ("Federal Unemployment (940)", None, None, None, "0.00"),
                ("FUTA Employer", "40000.00", "40000.00", "0.00", "0.00"),
                ("NYS Employment Taxes", None, None, None, "0.00"),
                ("NY Re-employment", "40000.00", "40000.00", "0.00", "0.00"),
                ("NY SUI Employer", "40000.00", "40000.00", "0.00", "0.00"),
                ("NYS Income Tax", None, None, None, "2860.02"),
                ("NY Income Tax", "40000.00", "0.00", "40000.00", "2860.02"),
            ],
        )

    def test_group_rows_leave_the_wage_columns_blank(self):
        """Several taxes ride the same wages; summing them would double-count."""
        for row in self.report["rows"]:
            if row["is_group"]:
                self.assertIsNone(row["total_wages"], row["label"])
                self.assertIsNone(row["excess_wages"], row["label"])
                self.assertIsNone(row["taxable_wages"], row["label"])

    def test_total_always_splits_into_excess_plus_taxable(self):
        for row in self.report["rows"]:
            if row["is_group"]:
                continue
            self.assertEqual(
                Decimal(row["excess_wages"]) + Decimal(row["taxable_wages"]),
                Decimal(row["total_wages"]),
                row["label"],
            )

    def test_columns(self):
        self.assertEqual(
            [c["key"] for c in self.report["columns"]],
            ["tax_type", "total_wages", "excess_wages", "taxable_wages",
             "tax_amount"],
        )


class WageBaseTests(TestCase):
    def test_federal_bases_come_from_the_statutory_table(self):
        self.assertEqual(
            resolve_wage_base("FUTA_EMPLOYER", year=2026), Decimal("7000")
        )
        self.assertEqual(
            resolve_wage_base("SOCIAL_SECURITY", year=2026), Decimal("184500")
        )

    def test_state_unemployment_reads_the_state_config(self):
        self.assertEqual(
            resolve_wage_base("NYS_UI_EMPLOYER", year=2026, state_config=NY_CONFIG),
            Decimal("12800"),
        )

    def test_the_nested_state_config_shape_also_works(self):
        """Not every state puts the base at the top level."""
        self.assertEqual(
            resolve_wage_base(
                "CA_UI_EMPLOYER",
                year=2026,
                state_config={"californiaUI": {"wageBase": 7000}},
            ),
            Decimal("7000"),
        )

    def test_uncapped_taxes_have_no_base(self):
        self.assertIsNone(resolve_wage_base("FEDERAL_INCOME_TAX", year=2026))
        self.assertIsNone(resolve_wage_base("MEDICARE", year=2026))

    def test_an_unresolvable_state_base_is_treated_as_uncapped(self):
        """Safe direction -- never invent an exemption."""
        self.assertIsNone(
            resolve_wage_base("XX_UI_EMPLOYER", year=2026, state_config={})
        )


class WageSplitTests(TestCase):
    def build(self, prior, wages="10000.00"):
        return {
            row["label"]: row
            for row in build_tax_and_wage_summary(
                [
                    payroll(
                        [
                            component("Salary", "PAY", wages),
                            component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "42.00"),
                        ]
                    )
                ],
                state_code="NY",
                year=2026,
                prior_wages={1: Decimal(prior)},
                state_config=NY_CONFIG,
            )["rows"]
        }

    def test_a_fresh_employee_uses_the_base_then_spills(self):
        row = self.build("0.00")["FUTA Employer"]
        self.assertEqual(row["taxable_wages"], "7000.00")
        self.assertEqual(row["excess_wages"], "3000.00")

    def test_a_partly_used_base_only_has_the_remainder(self):
        row = self.build("5000.00")["FUTA Employer"]
        self.assertEqual(row["taxable_wages"], "2000.00")
        self.assertEqual(row["excess_wages"], "8000.00")

    def test_an_exhausted_base_makes_everything_excess(self):
        row = self.build("7000.00")["FUTA Employer"]
        self.assertEqual(row["taxable_wages"], "0.00")
        self.assertEqual(row["excess_wages"], "10000.00")

    def test_wages_under_the_base_are_wholly_taxable(self):
        row = self.build("0.00", wages="1000.00")["FUTA Employer"]
        self.assertEqual(row["taxable_wages"], "1000.00")
        self.assertEqual(row["excess_wages"], "0.00")


class PerEmployeeTests(TestCase):
    def test_the_cap_applies_per_person_not_to_the_company_total(self):
        """Two employees at 5,000 each are both under a 7,000 base."""
        report = build_tax_and_wage_summary(
            [
                payroll(
                    [
                        component("Salary", "PAY", "5000.00"),
                        component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "30.00"),
                    ],
                    employee_id=1,
                ),
                payroll(
                    [
                        component("Salary", "PAY", "5000.00"),
                        component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "30.00"),
                    ],
                    employee_id=2,
                ),
            ],
            state_code="NY",
            year=2026,
        )
        row = next(r for r in report["rows"] if r["label"] == "FUTA Employer")
        self.assertEqual(row["total_wages"], "10000.00")
        self.assertEqual(row["excess_wages"], "0.00")
        self.assertEqual(row["taxable_wages"], "10000.00")

    def test_total_wages_counts_only_employees_who_incurred_the_tax(self):
        report = build_tax_and_wage_summary(
            [
                payroll(
                    [
                        component("Salary", "PAY", "5000.00"),
                        component("MEDICARE", "EMPLOYEE_TAXES", "72.50"),
                        component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "30.00"),
                    ],
                    employee_id=1,
                ),
                payroll(
                    [
                        component("Salary", "PAY", "3000.00"),
                        component("MEDICARE", "EMPLOYEE_TAXES", "43.50"),
                    ],
                    employee_id=2,
                ),
            ],
            state_code="NY",
            year=2026,
        )
        rows = {r["label"]: r for r in report["rows"]}
        self.assertEqual(rows["Medicare"]["total_wages"], "8000.00")
        # Only employee 1 had FUTA.
        self.assertEqual(rows["FUTA Employer"]["total_wages"], "5000.00")


class TotalPayrollCostTests(TestCase):
    def setUp(self):
        self.report = build_total_payroll_cost([payroll(reference_components())])
        self.rows = [(r["label"], r["kind"], r["amount"]) for r in self.report["rows"]]

    def test_matches_the_reference_line_for_line(self):
        self.assertEqual(
            self.rows,
            [
                ("Total pay", "group", None),
                ("Paycheck wages", "item", "40000.00"),
                ("Non-paycheck wages", "item", "0.00"),
                ("Reimbursements", "item", "0.00"),
                ("Subtotal", "subtotal", "40000.00"),
                ("Company contributions", "group", None),
                ("Subtotal", "subtotal", "0.00"),
                ("Employer taxes", "group", None),
                ("Social Security Employer", "item", "2480.00"),
                ("Medicare Employer", "item", "580.00"),
                ("FUTA Employer", "item", "0.00"),
                ("NY Re-employment", "item", "0.00"),
                ("NY SUI Employer", "item", "0.00"),
                ("Subtotal", "subtotal", "3060.00"),
                ("Total payroll cost", "total", "43060.00"),
            ],
        )

    def test_group_rows_carry_no_amount(self):
        for row in self.report["rows"]:
            if row["kind"] == "group":
                self.assertIsNone(row["amount"], row["label"])

    def test_the_ladder_adds_up(self):
        rows = {row["key"]: row for row in self.report["rows"]}
        self.assertEqual(
            Decimal(rows["total_pay.subtotal"]["amount"])
            + Decimal(rows["company_contributions.subtotal"]["amount"])
            + Decimal(rows["employer_taxes.subtotal"]["amount"]),
            Decimal(rows["total_payroll_cost"]["amount"]),
        )

    def test_employee_taxes_are_not_a_company_cost(self):
        """They come out of the employee's gross, which is already counted."""
        labels = [row["label"] for row in self.report["rows"]]
        self.assertNotIn("Federal Income Tax", labels)
        self.assertNotIn("Social Security", labels)

    def test_contributions_appear_when_present(self):
        report = build_total_payroll_cost(
            [
                payroll(
                    [
                        component("Salary", "PAY", "1000.00"),
                        component("Health", "COMPANY_PAID_CONTRIBUTIONS", "75.00"),
                    ]
                )
            ]
        )
        rows = {row["key"]: row for row in report["rows"]}
        self.assertEqual(rows["company_contributions.Health"]["amount"], "75.00")
        self.assertEqual(
            rows["company_contributions.subtotal"]["amount"], "75.00"
        )
        self.assertEqual(rows["total_payroll_cost"]["amount"], "1075.00")

    def test_empty_payroll_still_returns_the_ladder(self):
        report = build_total_payroll_cost([])
        rows = {row["key"]: row for row in report["rows"]}
        self.assertEqual(rows["total_payroll_cost"]["amount"], "0.00")
        self.assertEqual(rows["paycheck_wages"]["amount"], "0.00")


class MultiStateWageBaseTests(TestCase):
    """A state tax must use its own state's base, not the company's."""

    CONFIGS = {"MN": {"uiWageBase": 44000}, "NY": {"uiWageBase": 12800}}

    def test_each_state_uses_its_own_base(self):
        from payrollio.django_rest.helpers.payroll_tax_wage_summary import state_of

        self.assertEqual(state_of("MN_UI_EMPLOYER"), "MN")
        self.assertEqual(state_of("NYS_UI_EMPLOYER"), "NY")
        self.assertEqual(state_of("NY_RSF"), "NY")
        self.assertIsNone(state_of("FUTA_EMPLOYER"))

        self.assertEqual(
            resolve_wage_base("MN_UI_EMPLOYER", year=2026, state_configs=self.CONFIGS),
            Decimal("44000"),
        )
        self.assertEqual(
            resolve_wage_base("NYS_UI_EMPLOYER", year=2026, state_configs=self.CONFIGS),
            Decimal("12800"),
        )

    def test_a_minnesota_company_does_not_charge_ny_against_the_mn_base(self):
        report = build_tax_and_wage_summary(
            [
                payroll(
                    [
                        component("Salary", "PAY", "60000.00"),
                        component("NYS_UI_EMPLOYER", "EMPLOYER_TAXES", "100.00"),
                    ]
                )
            ],
            state_code="MN",
            year=2026,
            state_configs=self.CONFIGS,
        )
        row = next(r for r in report["rows"] if r["label"] == "NY SUI Employer")
        # NY's 12,800 base, not Minnesota's 44,000.
        self.assertEqual(row["taxable_wages"], "12800.00")
        self.assertEqual(row["excess_wages"], "47200.00")
