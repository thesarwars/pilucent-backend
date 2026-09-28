"""Tests for the tax liability report.

Exercises the grouping and the paid/owed arithmetic against light stand-ins;
`resolve_paid_by_group` needs the ORM and is covered by the production probe
rather than here.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAX_GROUP_940,
    FEDERAL_TAX_GROUP_941,
)
from payrollio.django_rest.helpers.payroll_tax_liability import (
    build_tax_liability,
    known_groups,
)
from payrollio.tests.test_payroll_summary_by_employee import component


def payroll(components):
    return SimpleNamespace(payroll_components=SimpleNamespace(all=lambda: components))


def reference_payroll():
    return payroll(
        [
            # Pay lines must not reach a tax report.
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
    )


def quads(report):
    return [
        (r["label"], r["tax_amount"], r["tax_paid"], r["tax_owed"], r["is_group"])
        for r in report["rows"]
    ]


class ReferenceReportTests(TestCase):
    """Reproduce the printed report the spec was taken from."""

    def setUp(self):
        self.report = build_tax_liability([reference_payroll()], state_code="NY")

    def test_matches_the_reference_line_for_line(self):
        self.assertEqual(
            quads(self.report),
            [
                ("Federal Taxes (941/943/944)", "17047.85", "0.00", "17047.85", True),
                ("Federal Income Tax", "10927.85", "0.00", "10927.85", False),
                ("Social Security", "2480.00", "0.00", "2480.00", False),
                ("Social Security Employer", "2480.00", "0.00", "2480.00", False),
                ("Medicare", "580.00", "0.00", "580.00", False),
                ("Medicare Employer", "580.00", "0.00", "580.00", False),
                ("Federal Unemployment (940)", "0.00", "0.00", "0.00", True),
                ("FUTA Employer", "0.00", "0.00", "0.00", False),
                ("NYS Employment Taxes", "0.00", "0.00", "0.00", True),
                ("NY Re-employment", "0.00", "0.00", "0.00", False),
                ("NY SUI Employer", "0.00", "0.00", "0.00", False),
                ("NYS Income Tax", "2860.02", "0.00", "2860.02", True),
                ("NY Income Tax", "2860.02", "0.00", "2860.02", False),
            ],
        )

    def test_pay_components_are_excluded(self):
        """Wages are not a tax liability."""
        self.assertNotIn(
            "Salary", [row["label"] for row in self.report["rows"]]
        )

    def test_group_total_is_the_sum_of_its_members(self):
        rows = {row["key"]: row for row in self.report["rows"]}
        members = [
            row for key, row in rows.items()
            if key.startswith(f"{FEDERAL_TAX_GROUP_941}.")
        ]
        self.assertEqual(
            sum(Decimal(row["tax_amount"]) for row in members),
            Decimal(rows[FEDERAL_TAX_GROUP_941]["tax_amount"]),
        )

    def test_columns(self):
        self.assertEqual(
            [c["key"] for c in self.report["columns"]],
            ["tax_type", "tax_amount", "tax_paid", "tax_owed"],
        )


class GroupOrderTests(TestCase):
    def test_federal_groups_lead_then_the_company_state(self):
        self.assertEqual(
            [key for key, _ in known_groups("NY")],
            [
                FEDERAL_TAX_GROUP_941,
                FEDERAL_TAX_GROUP_940,
                "NYS_EMPLOYMENT_TAXES",
                "NYS_INCOME_TAX",
            ],
        )

    def test_employment_prints_above_income(self):
        """The declared tuple lists income first; the report does not."""
        labels = [label for _, label in known_groups("NY")]
        self.assertLess(
            labels.index("NYS Employment Taxes"), labels.index("NYS Income Tax")
        )

    def test_only_the_companys_own_state_is_offered(self):
        keys = [key for key, _ in known_groups("MN")]
        self.assertNotIn("NYS_INCOME_TAX", keys)
        self.assertIn("MN_INCOME_TAX", keys)

    def test_unknown_state_still_gets_the_federal_groups(self):
        self.assertEqual(
            [key for key, _ in known_groups(None)],
            [FEDERAL_TAX_GROUP_941, FEDERAL_TAX_GROUP_940],
        )


class EmptyGroupTests(TestCase):
    def test_a_group_with_no_components_is_omitted(self):
        report = build_tax_liability(
            [payroll([component("MEDICARE", "EMPLOYEE_TAXES", "10.00")])],
            state_code="NY",
        )
        labels = [row["label"] for row in report["rows"]]
        self.assertEqual(labels, ["Federal Taxes (941/943/944)", "Medicare"])

    def test_a_zero_component_still_prints(self):
        """The reference shows $0.00 lines -- absence and zero differ."""
        report = build_tax_liability(
            [payroll([component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "0.00")])],
            state_code="NY",
        )
        self.assertEqual(
            [row["label"] for row in report["rows"]],
            ["Federal Unemployment (940)", "FUTA Employer"],
        )

    def test_no_payrolls_returns_no_rows(self):
        self.assertEqual(build_tax_liability([], state_code="NY")["rows"], [])


class UngroupedTaxTests(TestCase):
    def test_a_tax_outside_every_group_is_surfaced_not_dropped(self):
        report = build_tax_liability(
            [
                payroll(
                    [
                        component("MEDICARE", "EMPLOYEE_TAXES", "10.00"),
                        component("SDI", "EMPLOYEE_TAXES", "6.00"),
                        component("FLI", "EMPLOYEE_TAXES", "4.00"),
                    ]
                )
            ],
            state_code="NY",
        )
        rows = {row["key"]: row for row in report["rows"]}
        self.assertIn("OTHER_TAXES", rows)
        self.assertEqual(rows["OTHER_TAXES"]["tax_amount"], "10.00")
        self.assertIn("OTHER_TAXES.SDI", rows)
        self.assertIn("OTHER_TAXES.FLI", rows)


class PaymentTests(TestCase):
    def build(self, paid_by_group):
        return build_tax_liability(
            [reference_payroll()], state_code="NY", paid_by_group=paid_by_group
        )

    def test_a_group_payment_reduces_what_is_owed(self):
        report = self.build({FEDERAL_TAX_GROUP_941: Decimal("1000.00")})
        rows = {row["key"]: row for row in report["rows"]}
        group = rows[FEDERAL_TAX_GROUP_941]
        self.assertEqual(group["tax_paid"], "1000.00")
        self.assertEqual(group["tax_owed"], "16047.85")

    def test_members_are_allocated_pro_rata_and_sum_to_the_group(self):
        report = self.build({FEDERAL_TAX_GROUP_941: Decimal("1000.00")})
        rows = {row["key"]: row for row in report["rows"]}
        members = [
            row for key, row in rows.items()
            if key.startswith(f"{FEDERAL_TAX_GROUP_941}.")
        ]
        self.assertEqual(
            sum(Decimal(row["tax_paid"]) for row in members), Decimal("1000.00")
        )
        # Federal Income Tax is 10927.85/17047.85 of the group: 641.0104.
        self.assertEqual(
            rows[f"{FEDERAL_TAX_GROUP_941}.FEDERAL_INCOME_TAX"]["tax_paid"], "641.01"
        )

    def test_overpayment_never_shows_a_negative_owed(self):
        report = self.build({FEDERAL_TAX_GROUP_941: Decimal("99999.00")})
        for row in report["rows"]:
            self.assertFalse(Decimal(row["tax_owed"]) < 0, row["label"])

    def test_a_group_with_zero_liability_absorbs_no_allocation(self):
        report = self.build({FEDERAL_TAX_GROUP_940: Decimal("50.00")})
        rows = {row["key"]: row for row in report["rows"]}
        # FUTA is 0.00, so there is nothing to allocate against.
        self.assertEqual(rows[f"{FEDERAL_TAX_GROUP_940}.FUTA_EMPLOYER"]["tax_paid"],
                         "0.00")

    def test_unpaid_groups_are_untouched(self):
        report = self.build({FEDERAL_TAX_GROUP_941: Decimal("1000.00")})
        rows = {row["key"]: row for row in report["rows"]}
        self.assertEqual(rows["NYS_INCOME_TAX"]["tax_paid"], "0.00")
        self.assertEqual(rows["NYS_INCOME_TAX"]["tax_owed"], "2860.02")


class MultiStateTests(TestCase):
    """A company running payroll in more than its own state."""

    def setUp(self):
        self.report = build_tax_liability(
            [
                payroll(
                    [
                        component("MEDICARE", "EMPLOYEE_TAXES", "10.00"),
                        component("MN_INCOME_TAX", "EMPLOYEE_TAXES", "20.00"),
                        component("_INCOME_TAX", "EMPLOYEE_TAXES", "30.00"),
                        component("NYS_UI_EMPLOYER", "EMPLOYER_TAXES", "40.00"),
                    ]
                )
            ],
            state_code="MN",
        )
        self.rows = {row["key"]: row for row in self.report["rows"]}

    def test_another_states_taxes_get_their_own_group(self):
        """Not dumped into "Other taxes" just because it is not the home state."""
        self.assertIn("NYS_EMPLOYMENT_TAXES", self.rows)
        self.assertEqual(self.rows["NYS_EMPLOYMENT_TAXES"]["tax_amount"], "40.00")

    def test_the_home_state_is_ordered_first(self):
        keys = [row["key"] for row in self.report["rows"] if row["is_group"]]
        self.assertLess(keys.index("MN_INCOME_TAX"), keys.index("NYS_EMPLOYMENT_TAXES"))

    def test_the_generic_state_income_key_is_counted_once(self):
        """`_INCOME_TAX` is a declared member of every state's income group."""
        appearances = [
            key for key in self.rows if key.endswith("._INCOME_TAX")
        ]
        self.assertEqual(len(appearances), 1, appearances)
        # It belongs to the home state, and is not double-counted into a total.
        self.assertEqual(self.rows["MN_INCOME_TAX"]["tax_amount"], "50.00")

    def test_every_component_is_counted_exactly_once(self):
        members = [
            Decimal(row["tax_amount"])
            for row in self.report["rows"]
            if not row["is_group"]
        ]
        self.assertEqual(sum(members), Decimal("100.00"))
