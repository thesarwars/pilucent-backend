"""Statutory computations (doc §6.3, §7; acceptance tests 9 and 13).

Test 9: floor-dividing months counted 6y 6m 20d of service as 6 gratuity years
-- understating exactly the records built to test it. Test 13: dividing days
present by 30 paid a full February at 28/30 = 0.9333 of a month.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from employeeio.choices import ProrationDivisorChoices as D
from employeeio.models import EmployeeSalaryComponent, EmployeeSalaryStructure
from employeeio.services.profile import service_parts
from employeeio.services.statutory import (
    earned_leave_accrual,
    festival_bonus,
    gratuity,
    gratuity_breakpoint,
    gratuity_days,
    gratuity_years,
    overtime_hourly,
    proration_factor,
    separation_entitlement,
)
from common.money import round_to_taka
from employeeio.test_support import AS_OF, FrozenClockMixin, make_company, make_employee, seed_rules
from paysetio.test_support import FakeCalendar, join, set_election
from rulebookio.book import UnknownRule, rule_book


def structure(employee, basic, hra=0, da=0, effective_from=date(2010, 1, 1)):
    s = EmployeeSalaryStructure.objects.create(employee=employee, effective_from=effective_from, template="custom")
    for position, (code, amount) in enumerate([("BASIC", basic), ("HRA", hra), ("DA", da)]):
        if amount:
            EmployeeSalaryComponent.objects.create(structure=s, code=code, amount=Decimal(amount), position=position)
    return s


class StatutoryTestCase(FrozenClockMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")

    def setUp(self):
        super().setUp()
        self.book = rule_book(AS_OF)

    def employee(self, code="EMP-0142", **fields):
        return make_employee(self.company, code, **fields)


class GratuityTests(StatutoryTestCase):
    def years(self, joined, until):
        return gratuity_years(service_parts(joined, until), self.book)[0]

    def test_six_years_six_months_twenty_days_is_seven(self):
        """Acceptance test 9."""
        parts = service_parts(date(2020, 8, 16), date(2027, 3, 8))
        self.assertEqual((parts.years, parts.residual_months, parts.residual_days), (6, 6, 20))
        self.assertEqual(self.years(date(2020, 8, 16), date(2027, 3, 8)), 7)  # 6y 6m 20d
        self.assertEqual(self.years(date(2020, 9, 8), date(2027, 3, 8)), 6)  # 6y 6m 0d: not over six months
        self.assertEqual(self.years(date(2020, 9, 7), date(2027, 3, 8)), 7)  # 6y 6m 1d

    def test_the_amount_on_basic(self):
        employee = self.employee(doj=date(2020, 8, 16))
        g = gratuity(employee, structure(employee, 13200, hra=6600), AS_OF, self.book)
        self.assertEqual((g.years, g.days, g.rounded_up), (7, 30, True))
        self.assertEqual(g.amount.value, Decimal("92400"))  # 13,200 / 30 x 30 x 7
        self.assertEqual(g.monthly_provision.value, Decimal("1100.00"))  # one year's 13,200 / 12
        self.assertIn("rounds up", g.amount.basis)

    def test_the_basis_can_be_gross(self):
        employee = self.employee(doj=date(2020, 8, 16))
        set_election(self.company, "gratuity_basis", "GROSS")
        g = gratuity(employee, structure(employee, 13200, hra=6600), AS_OF, self.book)
        self.assertEqual(g.amount.value, Decimal("138600"))  # 19,800 / 30 x 30 x 7

    def test_forty_five_days_only_above_ten_years(self):
        self.assertEqual(gratuity_days(10, self.book), 30)
        self.assertEqual(gratuity_days(11, self.book), 45)

    def test_the_breakpoint_is_exposed_before_it_bites(self):
        # 10 years plus a part-year over six months rounds to 11, the first
        # count above the breakpoint.
        employee = self.employee(doj=date(2016, 12, 1))
        s = structure(employee, 12000)
        crossing = gratuity_breakpoint(employee, s, AS_OF, self.book)
        self.assertEqual(crossing["anniversary"], "2026-12-01")
        self.assertEqual(crossing["ratesRiseOn"], "2027-06-02")
        self.assertTrue(crossing["withinTwelveMonths"])
        self.assertEqual((crossing["daysFrom"], crossing["daysTo"]), (30, 45))
        self.assertEqual(crossing["monthlyProvisionAfter"]["value"], "1500.00")  # 12,000 / 30 x 45 / 12
        self.assertEqual(gratuity_days(self.years(employee.doj, date(2027, 6, 2)), self.book), 45)
        self.assertEqual(gratuity_days(self.years(employee.doj, date(2027, 6, 1)), self.book), 30)
        # Once crossed, nothing to warn about.
        self.assertIsNone(gratuity_breakpoint(employee, s, date(2027, 6, 2), self.book))


class OvertimeBonusLeaveTests(StatutoryTestCase):
    def test_overtime_is_on_basic_and_da_only(self):
        employee = self.employee()
        hourly = overtime_hourly(employee, structure(employee, 13200, hra=6600, da=1000), self.book, AS_OF)
        self.assertEqual(hourly.value, Decimal("136.54"))  # (13,200 + 1,000) / 208 x 2
        self.assertEqual(hourly.citation, "Bangladesh Labour Act 2006, s.108")
        # The multiplier is VERIFIED; the 208-hour divisor only CORROBORATED.
        self.assertEqual(hourly.confidence, "CORROBORATED")

    def test_festival_bonus_after_twelve_months(self):
        joined = self.employee(doj=date(2026, 3, 9))
        bonus = festival_bonus(joined, structure(joined, 13200), AS_OF, self.book)
        self.assertEqual((bonus["eligibleFrom"], bonus["eligible"]), ("2027-03-09", False))
        self.assertEqual((bonus["perBonus"]["value"], bonus["annual"]["value"]), ("13200.00", "26400.00"))
        self.assertEqual(bonus["monthlyProvision"]["value"], "2200.00")
        self.assertEqual(bonus["taxable"]["value"], True)
        earlier = self.employee("EMP-0001", doj=date(2026, 3, 8))
        self.assertTrue(festival_bonus(earlier, structure(earlier, 13200), AS_OF, self.book)["eligible"])

    def test_earned_leave_by_establishment(self):
        self.assertEqual(earned_leave_accrual(180, "FACTORY", self.book), 10)
        self.assertEqual(earned_leave_accrual(180, "TEA_PLANTATION", self.book), 8)
        self.assertEqual(earned_leave_accrual(180, "NEWSPAPER", self.book), 16)
        with self.assertRaises(UnknownRule):
            earned_leave_accrual(180, "", self.book)
        self.assertEqual(self.book.labour.value("festivalHolidayDays"), 13)


class ProrationTests(StatutoryTestCase):
    """Payroll settings §4.3 and golden vectors S1/S2."""

    cal = FakeCalendar(off=(5,))  # a Friday weekly holiday

    def test_a_full_february_is_a_full_month(self):
        """Salary profile acceptance test 13: 1.0, not 28/30 = 0.9333."""
        february = date(2027, 2, 1)
        for method in D.values:
            with self.subTest(method=method):
                self.assertEqual(proration_factor(february, method, self.book, calendar=self.cal), 1)

    def test_s1_one_joiner_four_methods(self):
        """৳50,000, a 31-day month, 19 payable calendar days; 18 payable
        working days of 27 (the spec's counts, from a calendar stub)."""

        class Counts:
            def working_days(self, first, last):
                return 27 if first.day == 1 else 18

        october, joined = date(2026, 10, 1), date(2026, 10, 13)
        amount = {m: round_to_taka(Decimal(50000) * proration_factor(october, m, self.book, join_date=joined,
                                                                     calendar=Counts())) for m in D.values}
        self.assertEqual(amount, {D.CALENDAR_DAYS: 30645, D.FIXED_30: 31667, D.WORKING_DAYS_26: 34615,
                                  D.ACTUAL_WORKING_DAYS: 33333})
        self.assertEqual(max(amount.values()) - min(amount.values()), 3970)

    def test_working_days_come_from_the_calendar(self):
        cal = FakeCalendar(off=(5,))  # Fridays 2, 9, 16, 23, 30 October 2026
        october = date(2026, 10, 1)
        self.assertEqual(cal.working_days(date(2026, 10, 1), date(2026, 10, 31)), 26)
        joined = date(2026, 10, 10)  # 22 calendar days, 19 working
        self.assertEqual(proration_factor(october, D.ACTUAL_WORKING_DAYS, self.book, join_date=joined, calendar=cal),
                         Decimal(19) / 26)
        two_day = FakeCalendar(off=(5, 6))
        self.assertEqual(proration_factor(october, D.ACTUAL_WORKING_DAYS, self.book, join_date=joined,
                                          calendar=two_day), Decimal(15) / 21)

    def test_s2_a_30_day_month_agrees_for_calendar_and_fixed_30(self):
        november = date(2026, 11, 1)
        joined = date(2026, 11, 12)
        self.assertEqual(proration_factor(november, D.CALENDAR_DAYS, self.book, join_date=joined),
                         proration_factor(november, D.FIXED_30, self.book, join_date=joined))

    def test_a_part_month_never_exceeds_a_whole_one(self):
        # FIXED_30 on a 31-day month: a joiner on the 1st is a whole month, 1.0, not 31/30.
        self.assertEqual(proration_factor(date(2026, 10, 1), D.FIXED_30, self.book, join_date=date(2026, 10, 1)), 1)
        self.assertEqual(proration_factor(date(2027, 2, 1), D.FIXED_30, self.book, join_date=date(2027, 3, 1)), 0)

    def test_working_day_methods_need_the_calendar(self):
        with self.assertRaises(ValueError):
            proration_factor(date(2026, 10, 1), D.WORKING_DAYS_26, self.book, join_date=date(2026, 10, 13))


class SeparationTests(StatutoryTestCase):
    def entitlement(self, kind, joined, basic=30000, until=AS_OF, eligible=True, **kwargs):
        employee = self.employee(f"EMP-{kind[:4]}{joined:%y%m%d}{'' if eligible else 'N'}", doj=joined)
        if eligible:
            join(employee, "GRATUITY")
        return separation_entitlement(employee, structure(employee, basic), kind, until, self.book, **kwargs)

    def test_termination_pays_the_higher_of_compensation_and_gratuity(self):
        result = self.entitlement("TERMINATION", date(2021, 3, 8))  # 6 years
        self.assertEqual((result["daysPerYear"], result["higherOfGratuity"]), (30, True))
        self.assertEqual(result["compensation"]["value"], "180000.00")
        self.assertEqual(result["payable"]["value"], "180000.00")

    def test_resignation_resolves_its_band_before_using_it(self):
        """A bare `days` is undefined for a graduated rule: the band decides."""
        two = self.entitlement("RESIGNATION", date(2025, 3, 8))
        self.assertEqual((two["years"], two["daysPerYear"], two["higherOfGratuity"]), (2, 7, False))
        self.assertEqual(two["payable"]["value"], "14000.00")  # 30,000 / 30 x 7 x 2
        self.assertEqual(two["rule"]["confidence"], "DISPUTED")
        five = self.entitlement("RESIGNATION", date(2022, 3, 8))
        self.assertEqual((five["daysPerYear"], five["payable"]["value"]), (15, "75000.00"))
        twelve = self.entitlement("RESIGNATION", date(2015, 3, 8))
        # 30 days, or gratuity at 45 days above ten years -- gratuity is higher.
        self.assertEqual((twelve["daysPerYear"], twelve["higherOfGratuity"], twelve["winner"]), (30, True, "GRATUITY"))
        self.assertEqual(twelve["payable"]["value"], "540000.00")
        under = self.entitlement("RESIGNATION", date(2026, 12, 1))
        self.assertEqual((under["band"], under["daysPerYear"]), (None, 0))

    def test_eligibility_is_on_completed_years_and_only_the_multiplier_rounds(self):
        # 2y 8m: the 1-3 band on completed years, paid on 3 rounded years.
        result = self.entitlement("RESIGNATION", date(2024, 7, 8))
        self.assertEqual((result["completedYears"], result["years"], result["daysPerYear"]), (2, 3, 7))
        self.assertEqual(result["payable"]["value"], "21000.00")  # 30,000 / 30 x 7 x 3
        # Seven months rounds to a year of gratuity, but is not a year of service.
        seven_months = self.entitlement("DISMISSAL", date(2026, 8, 1))
        self.assertEqual((seven_months["years"], seven_months["daysPerYear"]), (1, 0))

    def test_gratuity_if_any_without_an_entitlement_compares_with_nil(self):
        result = self.entitlement("RESIGNATION", date(2015, 3, 8), eligible=False)
        self.assertEqual((result["gratuity"]["value"], result["winner"]), ("0.00", "COMPENSATION"))
        self.assertEqual(result["payable"]["value"], "360000.00")

    def test_death_steps_up_above_ten_years_and_needs_a_year(self):
        long = self.entitlement("DEATH", date(2015, 3, 8))
        self.assertEqual(long["daysPerYear"], 45)
        short = self.entitlement("DEATH", date(2026, 12, 1))
        self.assertEqual((short["years"], short["daysPerYear"]), (0, 0))

    def test_dismissal_for_gross_misconduct_is_nil(self):
        result = self.entitlement("DISMISSAL", date(2021, 3, 8), gross_misconduct=True)
        self.assertEqual((result["winner"], result["payable"]["value"]), ("NIL", "0.00"))
        ordinary = self.entitlement("DISMISSAL", date(2020, 3, 8))
        self.assertEqual((ordinary["daysPerYear"], ordinary["payable"]["value"]), (15, "105000.00"))
