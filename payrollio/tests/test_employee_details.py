"""Tests for the employee details report.

The masking assertions are the important ones: a regression there leaks a real
SSN, birth year or bank account onto a shared PDF.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from payrollio.django_rest.helpers.employee_details import (
    build_employee_details,
    mask_tail,
    masked_birth_date,
    time_off_category,
)


def employee(
    uid="emp-1",
    first_name="Ab. Rahim",
    last_name="Babu",
    middle_name="",
    ssn="473497764",
    date_of_birth=date(1986, 4, 30),
    gender="MALE",
    total_salary="50000.000",
    total_rate_per_hour="0.000",
    salary_frequency="PER_YEAR",
    confirmation_date=date(2025, 5, 1),
    offer_date=None,
    description="",
    work_locations=None,
    employee_id=1,
):
    return SimpleNamespace(
        id=employee_id,
        uid=uid,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        ssn=ssn,
        date_of_birth=date_of_birth,
        gender=gender,
        total_salary=Decimal(total_salary),
        total_rate_per_hour=Decimal(total_rate_per_hour),
        salary_frequency=salary_frequency,
        confirmation_date=confirmation_date,
        offer_date=offer_date,
        description=description,
        work_locations=work_locations,
        user=SimpleNamespace(name=f"{first_name} {last_name}"),
    )


def work_location(address="101 Calistoga St E", city="Orting", state="WA",
                  zip_code="98360-2077"):
    return SimpleNamespace(
        location_address=address,
        location_city=city,
        location_state=state,
        location_zip=zip_code,
    )


def address(full_address="101 Calistoga St E", city="Orting", province="WA",
            postal_code="98360-2077"):
    return SimpleNamespace(
        full_address=full_address,
        street="",
        city=city,
        province=province,
        postal_code=postal_code,
    )


def banking(number="204792596189"):
    return SimpleNamespace(bank_account_number=number)


def dedcon(name, employee_amount="0.000", company_amount="0.000",
           category=None):
    return SimpleNamespace(
        deduction_and_contribution=SimpleNamespace(
            title=name, sub_type=None, deduction_type=category
        ),
        total_employee_deduction_per_pay_check=Decimal(employee_amount),
        total_company_contribution_per_pay_check=Decimal(company_amount),
    )


def allocation(name, display_name=None):
    return SimpleNamespace(
        leave_type=SimpleNamespace(name=name, display_name=display_name)
    )


def tax(state="", holding_status="SINGLE_OR_MARRIED_FILING_SEPARATLEY",
        martial_status="UN_MARRIED", multi_jobs=False):
    return SimpleNamespace(
        state=state,
        holding_status=holding_status,
        martial_status=martial_status,
        is_multiple_jobs_or_spouse_works=multi_jobs,
    )


def pairs(entries):
    return [(e["label"], e["value"]) for e in entries]


class MaskingTests(TestCase):
    """A leak here ends up on a PDF someone emails."""

    def test_ssn_keeps_only_the_last_four(self):
        self.assertEqual(mask_tail("473497764"), "....7764")

    def test_bank_account_keeps_only_the_last_four(self):
        self.assertEqual(mask_tail("204792596189"), "....6189")

    def test_separators_do_not_shift_the_window(self):
        self.assertEqual(mask_tail("473-49-7764"), "....7764")

    def test_too_short_to_mask_returns_nothing(self):
        """Better empty than echoing a 3-digit value in full."""
        self.assertEqual(mask_tail("123"), "")
        self.assertEqual(mask_tail(""), "")
        self.assertEqual(mask_tail(None), "")

    def test_birth_year_is_withheld(self):
        self.assertEqual(masked_birth_date(date(1986, 4, 30)), "04/30/yyyy")

    def test_missing_birth_date_is_empty(self):
        self.assertEqual(masked_birth_date(None), "")

    def test_no_full_ssn_or_birth_year_reaches_the_payload(self):
        report = build_employee_details(
            [employee(ssn="473497764", date_of_birth=date(1986, 4, 30))]
        )
        blob = repr(report)
        self.assertNotIn("473497764", blob)
        self.assertNotIn("1986", blob)


class ReferenceRowTests(TestCase):
    """The first employee on the printed report."""

    def setUp(self):
        self.report = build_employee_details(
            [employee(work_locations=work_location())],
            related={
                1: {
                    "address": address(),
                    "banking": None,  # no banking -> Check
                    "deductions": [],
                    "contributions": [],
                    "allocations": [
                        allocation("Casual Leave"),
                        allocation("Sick Leave"),
                        allocation("no paid Leave"),
                        allocation("Leave policy"),
                    ],
                    "tax_rows": [tax(), tax(state="WA", holding_status="",
                                           martial_status="")],
                }
            },
        )
        self.row = self.report["rows"][0]

    def test_name_is_last_comma_first(self):
        self.assertEqual(self.row["name"], "Babu, Ab. Rahim")

    def test_personal_info(self):
        self.assertEqual(self.row["address"], "101 Calistoga St E, Orting, WA 98360-2077")
        self.assertEqual(self.row["date_of_birth"], "04/30/yyyy")
        self.assertEqual(self.row["gender"], "Male")

    def test_hire_date_falls_back_and_says_so(self):
        """There is no hire-date field; the row records which proxy was used."""
        self.assertEqual(self.row["hire_date"], date(2025, 5, 1))
        self.assertEqual(self.row["hire_date_source"], "confirmation_date")

    def test_work_location(self):
        self.assertEqual(
            self.row["work_location"], "101 Calistoga St E, Orting, WA 98360-2077"
        )

    def test_pay_info(self):
        self.assertEqual(
            pairs(self.row["pay_info"]),
            [
                ("Salary", ["$50,000.00/yr"]),
                ("Pay method", ["Check"]),
                ("Deductions", ["None"]),
                ("Contributions", ["None"]),
                (
                    "Time off",
                    ["Casual Leave", "Sick: Sick Leave", "Unpaid: no paid Leave",
                     "Leave policy"],
                ),
            ],
        )

    def test_tax_info_drops_the_blank_state_row(self):
        self.assertEqual(
            pairs(self.row["tax_info"]),
            [
                ("SSN", ["....7764"]),
                ("Fed", ["Single or Married Filing Separately"]),
            ],
        )

    def test_columns(self):
        self.assertEqual(
            [c["key"] for c in self.report["columns"]],
            ["personal_info", "hire_date", "work_location", "pay_info", "tax_info",
             "notes"],
        )


class PayInfoTests(TestCase):
    def build(self, **kwargs):
        related = {1: kwargs.pop("related", {})}
        report = build_employee_details([employee(**kwargs)], related=related)
        return {p["label"]: p["value"] for p in report["rows"][0]["pay_info"]}

    def test_hourly_wins_over_salary(self):
        info = self.build(total_rate_per_hour="40.000", total_salary="0.000")
        self.assertEqual(info["Hourly rate"], ["$40.00/hr"])
        self.assertNotIn("Salary", info)

    def test_frequency_suffix(self):
        self.assertEqual(
            self.build(salary_frequency="PER_MONTH")["Salary"], ["$50,000.00/mo"]
        )

    def test_an_employee_with_no_rate_omits_the_line(self):
        """Production and the reference both have one."""
        info = self.build(total_salary="0.000", total_rate_per_hour="0.000")
        self.assertNotIn("Salary", info)
        self.assertNotIn("Hourly rate", info)

    def test_direct_deposit_masks_the_account(self):
        info = self.build(related={"banking": banking("204792596189")})
        self.assertEqual(info["Pay method"], ["DD, ....6189"])

    def test_deductions_and_contributions_split_by_amount(self):
        info = self.build(
            related={
                "deductions": [
                    dedcon("Health Insurance", employee_amount="50.000"),
                    dedcon("child/spouse support", employee_amount="50.000"),
                    dedcon("Vision", employee_amount="0.000"),
                ],
                "contributions": [
                    dedcon("Health Insurance", company_amount="20.000"),
                    dedcon("Unused", company_amount="0.000"),
                ],
            }
        )
        self.assertEqual(
            info["Deductions"],
            ["Health Insurance: $50.00", "child/spouse support: $50.00"],
        )
        self.assertEqual(info["Contributions"], ["Health Insurance: $20.00"])

    def test_nothing_configured_reads_none(self):
        info = self.build()
        self.assertEqual(info["Deductions"], ["None"])
        self.assertEqual(info["Contributions"], ["None"])
        self.assertEqual(info["Time off"], ["None"])

    def test_duplicate_policies_appear_once(self):
        info = self.build(
            related={"allocations": [allocation("Sick Leave"), allocation("Sick Leave")]}
        )
        self.assertEqual(info["Time off"], ["Sick: Sick Leave"])

    def test_display_name_wins_over_name(self):
        info = self.build(
            related={"allocations": [allocation("internal", display_name="Vacation Plan")]}
        )
        self.assertEqual(info["Time off"], ["Vacation: Vacation Plan"])


class TimeOffCategoryTests(TestCase):
    def test_unambiguous_names_are_categorised(self):
        self.assertEqual(time_off_category("Sick Leave"), "Sick")
        self.assertEqual(time_off_category("Vacation policy"), "Vacation")
        self.assertEqual(time_off_category("no paid Leave"), "Unpaid")
        self.assertEqual(time_off_category("Unpaid time"), "Unpaid")

    def test_an_ambiguous_name_is_not_guessed(self):
        """Calling an unpaid policy "Paid" misstates someone's benefits."""
        self.assertIsNone(time_off_category("Casual Leave"))
        self.assertIsNone(time_off_category("Leave policy"))
        self.assertIsNone(time_off_category(""))

    def test_unpaid_beats_paid_when_both_words_appear(self):
        self.assertEqual(time_off_category("no paid Leave"), "Unpaid")


class TaxInfoTests(TestCase):
    def build(self, tax_rows):
        report = build_employee_details(
            [employee()], related={1: {"tax_rows": tax_rows}}
        )
        return {p["label"]: p["value"] for p in report["rows"][0]["tax_info"]}

    def test_federal_is_the_row_with_no_state(self):
        info = self.build([tax(state=""), tax(state="NY")])
        self.assertEqual(info["Fed"], ["Single or Married Filing Separately"])
        self.assertIn("NY", info)

    def test_multiple_jobs_is_appended(self):
        info = self.build(
            [
                tax(
                    holding_status="MARRIED_FILING_JOINTLY_OR_QUALIYING_WIDOW",
                    multi_jobs=True,
                )
            ]
        )
        self.assertEqual(
            info["Fed"],
            ["Married Filing Jointly or Qualifying Surviving Spouse Multiple jobs"],
        )

    def test_several_states_each_get_a_line(self):
        info = self.build(
            [tax(state=""), tax(state="CA"), tax(state="NY", martial_status="MARRIED")]
        )
        self.assertIn("CA", info)
        self.assertEqual(info["NY"], ["Single or Married Filing Separately"])

    def test_a_duplicate_state_appears_once(self):
        """Production has two MN rows, one entirely blank."""
        info = self.build([tax(state="MN"), tax(state="MN", holding_status="",
                                                martial_status="")])
        self.assertEqual(len(info["MN"]), 1)

    def test_marital_status_backs_up_a_missing_filing_status(self):
        info = self.build([tax(holding_status="", martial_status="MARRIED")])
        self.assertEqual(info["Fed"], ["Married"])

    def test_ssn_always_leads(self):
        report = build_employee_details([employee()], related={1: {"tax_rows": []}})
        self.assertEqual(report["rows"][0]["tax_info"][0]["label"], "SSN")


class OrderingTests(TestCase):
    def test_rows_sort_by_display_name(self):
        report = build_employee_details(
            [
                employee(uid="e1", first_name="Neymar", last_name="Junior",
                         employee_id=1),
                employee(uid="e2", first_name="John", last_name="Frankline",
                         employee_id=2),
                employee(uid="e3", first_name="Kamrul", last_name="Islam",
                         employee_id=3),
            ]
        )
        self.assertEqual(
            [row["name"] for row in report["rows"]],
            ["Frankline, John", "Islam, Kamrul", "Junior, Neymar"],
        )


class EmptyReportTests(TestCase):
    def test_no_employees_returns_no_rows(self):
        report = build_employee_details([])
        self.assertEqual(report["rows"], [])
        self.assertEqual(len(report["columns"]), 6)

    def test_an_employee_with_nothing_configured_still_renders(self):
        report = build_employee_details(
            [
                employee(
                    ssn="", date_of_birth=None, gender="", total_salary="0.000",
                    confirmation_date=None, work_locations=None,
                )
            ]
        )
        row = report["rows"][0]
        self.assertEqual(row["date_of_birth"], "")
        self.assertEqual(row["work_location"], "")
        self.assertIsNone(row["hire_date"])
        self.assertEqual(row["hire_date_source"], "")

    def test_offer_date_is_the_second_choice_for_hire_date(self):
        report = build_employee_details(
            [employee(confirmation_date=None, offer_date=date(2025, 2, 1))]
        )
        self.assertEqual(report["rows"][0]["hire_date"], date(2025, 2, 1))
        self.assertEqual(report["rows"][0]["hire_date_source"], "offer_date")


class SetupNameTests(TestCase):
    """The plan's own name, not the category it sits under."""

    def build(self, setup):
        report = build_employee_details(
            [employee()],
            related={
                1: {
                    "deductions": [
                        SimpleNamespace(
                            deduction_and_contribution=setup,
                            total_employee_deduction_per_pay_check=Decimal("7.800"),
                            total_company_contribution_per_pay_check=Decimal("0.000"),
                        )
                    ]
                }
            },
        )
        return {p["label"]: p["value"] for p in report["rows"][0]["pay_info"]}[
            "Deductions"
        ]

    def test_title_wins_over_category(self):
        """Production labelled three distinct plans "Health Insurance"."""
        setup = SimpleNamespace(
            title="Vision Plan", sub_type="vision", deduction_type="Health Insurance"
        )
        self.assertEqual(self.build(setup), ["Vision Plan: $7.80"])

    def test_sub_type_is_the_second_choice(self):
        setup = SimpleNamespace(
            title="", sub_type="dental", deduction_type="Health Insurance"
        )
        self.assertEqual(self.build(setup), ["dental: $7.80"])

    def test_category_is_the_last_resort(self):
        setup = SimpleNamespace(title="", sub_type="", deduction_type="HSA Plans")
        self.assertEqual(self.build(setup), ["HSA Plans: $7.80"])

    def test_an_unnamed_setup_still_shows_its_amount(self):
        setup = SimpleNamespace(title="", sub_type="", deduction_type="")
        self.assertEqual(self.build(setup), ["$7.80"])
