"""Tests for the time off and total pay reports."""

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from payrollio.django_rest.helpers.payroll_total_pay import (
    TOTAL_COLUMN_KEY,
    TOTAL_ROW_KEY,
    build_total_pay,
)
from payrollio.django_rest.helpers.time_off import (
    PAID,
    SICK,
    UNPAID,
    VACATION,
    build_time_off,
    categorise,
    format_balance,
    format_used,
)
from payrollio.tests.test_payroll_summary_by_employee import component, employee


def payroll(emp, components):
    return SimpleNamespace(
        employee=emp, payroll_components=SimpleNamespace(all=lambda: components)
    )


def leave_type(name, without_pay=False, display_name=None):
    return SimpleNamespace(
        name=name, display_name=display_name, is_leave_without_pay=without_pay
    )


def allocation(policy, balance="0.000", used_days=0):
    return SimpleNamespace(
        leave_type=policy,
        available_balance=Decimal(balance),
        used_days=used_days,
    )


def person(uid, first, last, employee_id):
    record = employee(uid, first, last)
    record.id = employee_id
    return record


# --------------------------------------------------------------------------
# Total pay
# --------------------------------------------------------------------------


class TotalPayReferenceTests(TestCase):
    def setUp(self):
        self.report = build_total_pay(
            [
                payroll(
                    employee("emp-1", "Abid Israk", "Ragib"),
                    [
                        component("Salary", "PAY", "40000.00", hours="173.33"),
                        # Taxes must not reach a pay report.
                        component("MEDICARE", "EMPLOYEE_TAXES", "580.00"),
                    ],
                )
            ]
        )

    def test_matches_the_reference(self):
        self.assertEqual(
            [c["label"] for c in self.report["columns"]], ["Name", "Salary", "Total"]
        )
        self.assertEqual(
            [(r["name"], r["values"]["Salary"], r["values"][TOTAL_COLUMN_KEY])
             for r in self.report["rows"]],
            [("Ragib, Abid Israk", "40000.00", "40000.00"),
             ("Total", "40000.00", "40000.00")],
        )

    def test_the_total_row_is_flagged_and_last(self):
        self.assertTrue(self.report["rows"][-1]["is_total"])
        self.assertEqual(self.report["rows"][-1]["key"], TOTAL_ROW_KEY)
        self.assertIsNone(self.report["rows"][-1]["employee_uid"])
        self.assertFalse(self.report["rows"][0]["is_total"])

    def test_taxes_are_excluded(self):
        self.assertNotIn("MEDICARE", [c["key"] for c in self.report["columns"]])


class TotalPayMultipleTests(TestCase):
    def setUp(self):
        self.report = build_total_pay(
            [
                payroll(
                    employee("emp-1", "Abid Israk", "Ragib"),
                    [component("Salary", "PAY", "1000.00")],
                ),
                payroll(
                    employee("emp-2", "Dana", "Abbott"),
                    [component("Hourly", "PAY", "500.00")],
                ),
                payroll(
                    employee("emp-1", "Abid Israk", "Ragib"),
                    [component("Bonus", "PAY", "250.00")],
                ),
            ]
        )
        self.rows = {row["key"]: row for row in self.report["rows"]}

    def test_a_column_per_pay_type(self):
        self.assertEqual(
            [c["key"] for c in self.report["columns"]],
            ["name", "Bonus", "Hourly", "Salary", TOTAL_COLUMN_KEY],
        )

    def test_rows_sort_by_name_with_total_last(self):
        self.assertEqual(
            [row["name"] for row in self.report["rows"]],
            ["Abbott, Dana", "Ragib, Abid Israk", "Total"],
        )

    def test_a_pay_type_an_employee_lacks_reads_zero(self):
        self.assertEqual(self.rows["emp-2"]["values"]["Salary"], "0.00")
        self.assertEqual(self.rows["emp-1"]["values"]["Hourly"], "0.00")

    def test_runs_accumulate_per_employee(self):
        self.assertEqual(self.rows["emp-1"]["values"][TOTAL_COLUMN_KEY], "1250.00")

    def test_the_total_row_sums_every_column(self):
        total = self.rows[TOTAL_ROW_KEY]["values"]
        self.assertEqual(total["Salary"], "1000.00")
        self.assertEqual(total["Hourly"], "500.00")
        self.assertEqual(total["Bonus"], "250.00")
        self.assertEqual(total[TOTAL_COLUMN_KEY], "1750.00")

    def test_every_row_spans_every_column(self):
        keys = {c["key"] for c in self.report["columns"]} - {"name"}
        for row in self.report["rows"]:
            self.assertEqual(set(row["values"]), keys, row["name"])


class TotalPayEmptyTests(TestCase):
    def test_no_payrolls_still_returns_a_total_row(self):
        report = build_total_pay([])
        self.assertEqual([c["key"] for c in report["columns"]],
                         ["name", TOTAL_COLUMN_KEY])
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["values"][TOTAL_COLUMN_KEY], "0.00")


# --------------------------------------------------------------------------
# Time off
# --------------------------------------------------------------------------


class CategoriseTests(TestCase):
    def test_without_pay_is_definitive(self):
        """The one category backed by a real field."""
        self.assertEqual(categorise(leave_type("Anything", without_pay=True)), UNPAID)

    def test_unpaid_by_name_when_the_flag_is_unset(self):
        self.assertEqual(categorise(leave_type("no paid Leave")), UNPAID)
        self.assertEqual(categorise(leave_type("Unpaid time")), UNPAID)

    def test_sick_and_vacation_come_from_the_name(self):
        self.assertEqual(categorise(leave_type("Sick Leave")), SICK)
        self.assertEqual(categorise(leave_type("Vacation policy")), VACATION)
        self.assertEqual(categorise(leave_type("Annual leave")), VACATION)

    def test_anything_else_paid_defaults_to_paid_time_off(self):
        self.assertEqual(categorise(leave_type("Casual Leave")), PAID)
        self.assertEqual(categorise(leave_type("Leave policy")), PAID)

    def test_the_flag_beats_a_sick_sounding_name(self):
        self.assertEqual(
            categorise(leave_type("Sick Leave", without_pay=True)), UNPAID
        )

    def test_display_name_is_matched_when_present(self):
        self.assertEqual(
            categorise(leave_type("internal", display_name="Sick days")), SICK
        )


class BalanceFormatTests(TestCase):
    def test_whole_days_keep_one_decimal(self):
        """The reference prints 90.0, not 90.00."""
        self.assertEqual(format_balance(Decimal("90.000")), "90.0")
        self.assertEqual(format_balance(Decimal("40.000")), "40.0")

    def test_fractions_keep_two(self):
        self.assertEqual(format_balance(Decimal("87.440")), "87.44")
        self.assertEqual(format_balance(Decimal("2.310")), "2.31")
        self.assertEqual(format_balance(Decimal("8.970")), "8.97")

    def test_absent_reads_zero(self):
        self.assertEqual(format_balance(None), "0")

    def test_used_is_a_whole_number(self):
        self.assertEqual(format_used(0), "0")
        self.assertEqual(format_used(3), "3")
        self.assertEqual(format_used(None), "0")


class TimeOffReferenceTests(TestCase):
    def setUp(self):
        babu = person("e1", "Ab. Rahim", "Babu", 1)
        frankline = person("e2", "John", "Frankline", 2)
        self.report = build_time_off(
            [babu, frankline],
            {
                1: [
                    allocation(leave_type("Sick Leave"), "90.000"),
                    allocation(leave_type("Casual Leave"), "87.440"),
                    allocation(leave_type("no paid Leave", without_pay=True), "90.000"),
                ],
                2: [allocation(leave_type("Casual Leave"), "40.000")],
            },
        )
        self.rows = {row["key"]: row for row in self.report["rows"]}

    def test_four_categories_paired_into_two_tables(self):
        self.assertEqual(
            [c["key"] for c in self.report["categories"]],
            [VACATION, SICK, PAID, UNPAID],
        )
        self.assertEqual(self.report["tables"], [[VACATION, SICK], [PAID, UNPAID]])

    def test_policies_land_in_their_slots(self):
        cells = self.rows["e1"]["categories"]
        self.assertEqual(cells[SICK]["policy"], "Sick Leave")
        self.assertEqual(cells[SICK]["balance"], "90.0")
        self.assertEqual(cells[PAID]["policy"], "Casual Leave")
        self.assertEqual(cells[PAID]["balance"], "87.44")
        self.assertEqual(cells[UNPAID]["policy"], "no paid Leave")
        self.assertEqual(cells[UNPAID]["balance"], "90.0")

    def test_an_unfilled_slot_reads_empty(self):
        """The renderer prints a dash for a null policy."""
        cells = self.rows["e1"]["categories"]
        self.assertIsNone(cells[VACATION]["policy"])
        self.assertEqual(cells[VACATION]["balance"], "0")
        self.assertEqual(cells[VACATION]["used"], "0")

    def test_an_employee_with_no_allocations_gets_four_empty_slots(self):
        report = build_time_off([person("e3", "Jim", "Sagor", 3)], {})
        cells = report["rows"][0]["categories"]
        self.assertEqual(len(cells), 4)
        for cell in cells.values():
            self.assertIsNone(cell["policy"])
            self.assertEqual(cell["balance"], "0")

    def test_every_row_carries_all_four_slots(self):
        for row in self.report["rows"]:
            self.assertEqual(
                set(row["categories"]), {VACATION, SICK, PAID, UNPAID}, row["name"]
            )

    def test_rows_sort_by_name(self):
        self.assertEqual(
            [row["name"] for row in self.report["rows"]],
            ["Babu, Ab. Rahim", "Frankline, John"],
        )


class TimeOffCollisionTests(TestCase):
    def test_two_policies_in_one_slot_add_up(self):
        """The report has room for one name, but must not lose the balance."""
        report = build_time_off(
            [person("e1", "Ab. Rahim", "Babu", 1)],
            {
                1: [
                    allocation(leave_type("Sick Leave"), "10.000", used_days=1),
                    allocation(leave_type("Medical Leave"), "5.500", used_days=2),
                ]
            },
        )
        cell = report["rows"][0]["categories"][SICK]
        self.assertEqual(cell["policy"], "Sick Leave")
        self.assertEqual(cell["balance"], "15.5")
        self.assertEqual(cell["used"], "3")

    def test_an_unnamed_policy_is_skipped(self):
        report = build_time_off(
            [person("e1", "Ab. Rahim", "Babu", 1)],
            {1: [allocation(leave_type(""), "10.000")]},
        )
        for cell in report["rows"][0]["categories"].values():
            self.assertIsNone(cell["policy"])


class TimeOffEmptyTests(TestCase):
    def test_no_employees_returns_no_rows(self):
        report = build_time_off([], {})
        self.assertEqual(report["rows"], [])
        self.assertEqual(len(report["categories"]), 4)
