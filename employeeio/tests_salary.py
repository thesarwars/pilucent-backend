"""Salary structures (doc §5, §6.2; acceptance tests 2 and 7).

The prototype defaulted a revision's effective date to the date of joining --
silently offering a nine-year backdate -- asserted template percentages as
fact on a statutory document, and checked one minimum-wage floor of two.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from employeeio.models import (
    CompanyStatutoryProfile,
    EmployeeFieldHistory,
    EmployeeSalaryComponent,
    EmployeeSalaryStructure,
    ProcessedPayrollPeriod,
)
from employeeio.services import salary
from employeeio.services.compliance import evaluate
from employeeio.services.salary import Built, build, floor_checks, structure_in_force, structure_out, warnings_for
from employeeio.test_support import (
    AS_OF,
    ApiMixin,
    FrozenClockMixin,
    give_structure,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
    url,
)
from rulebookio.book import rule_book


def amounts(built):
    return {code: int(amount) for code, amount in built.components}


class TemplateTests(FrozenClockMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()

    def setUp(self):
        super().setUp()
        self.book = rule_book(AS_OF)

    def test_standard_basic_balances_so_the_parts_sum_to_gross(self):
        self.assertEqual(amounts(build("std", Decimal("22000"), self.book)),
                         {"BASIC": 13200, "HRA": 6600, "MED": 1540, "CONV": 660})
        odd = build("std", Decimal("22050"), self.book)
        # Medical 1,543.5 and conveyance 661.5 round up; basic absorbs the difference.
        self.assertEqual(amounts(odd), {"BASIC": 13229, "HRA": 6615, "MED": 1544, "CONV": 662})
        self.assertEqual(odd.gross, Decimal("22050"))

    def test_classic_divides_by_one_and_a_half(self):
        built = build("classic", Decimal("22000"), self.book)
        self.assertEqual(amounts(built), {"BASIC": 14666, "HRA": 7334})
        self.assertEqual(built.gross, Decimal("22000"))

    def test_rmg_builds_up_from_the_gazetted_basic(self):
        """With no amount, basic is the grade's gazetted basic, and the
        gazetted allowances bring it to exactly the grade's total floor."""
        built = build("rmg", None, self.book, grade="G7")
        self.assertEqual(amounts(built), {"BASIC": 6700, "HRA": 3350, "MED": 750, "CONV": 450, "FOOD": 1250})
        self.assertEqual(built.gross, Decimal("12500"))
        self.assertTrue(all(c["passed"] for c in floor_checks("G7", built.basic, built.gross, self.book)))

    def test_effective_percentages_are_back_solved_never_the_templates(self):
        """§5.1: 58.6% of gross when that is what is on file, not the 60% the
        template would have given."""
        employee = make_employee(make_company("Rahman Garments"), "EMP-0142")
        structure = EmployeeSalaryStructure.objects.create(employee=employee, effective_from=date(2026, 7, 1),
                                                           template="std")
        for position, (code, amount) in enumerate([("BASIC", 12892), ("HRA", 6908), ("MED", 1540), ("CONV", 660)]):
            EmployeeSalaryComponent.objects.create(structure=structure, code=code, amount=amount, position=position)
        out = structure_out(structure)
        self.assertEqual(out["basicPercentOfGross"], "58.6")
        self.assertEqual(out["components"][0]["basis"], "58.6% of gross")
        self.assertEqual(out["grossInWords"]["en"], "Twenty two thousand taka only")

    def test_both_floors_with_separate_messages(self):
        """§5.3: a structure can clear the basic floor and fail the total."""
        built = build("std", Decimal("14000"), self.book)  # basic 8,400
        checks = {c["kind"]: c for c in floor_checks("G1", built.basic, built.gross, self.book)}
        self.assertTrue(checks["basic"]["passed"])
        self.assertFalse(checks["total"]["passed"])
        self.assertIn("below the gazetted total floor of ৳ 15,035 for G1", checks["total"]["message"])
        self.assertIn("s.289(1)", checks["total"]["message"])
        self.assertIn("Tk 50,000–1,00,000", checks["total"]["message"])
        self.assertEqual(checks["total"]["confidence"], "DRAFTED")

    def test_warnings_never_block(self):
        low = Built("custom", [("BASIC", Decimal("9000")), ("HRA", Decimal("11000"))])
        self.assertEqual([w["key"] for w in warnings_for(low, current_gross=Decimal("15000"))],
                         ["salary.largeIncrement", "salary.lowBasicShare"])
        # Exactly 25% is not over the threshold.
        self.assertEqual([w["key"] for w in warnings_for(low, current_gross=Decimal("16000"))],
                         ["salary.lowBasicShare"])


class SalaryApiTestCase(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.admin = make_user(cls.company, "admin@rahman.example")
        make_company_admin(cls.admin, cls.company)
        cls.member = make_user(cls.company, "hr@rahman.example")
        # Processed through February 2027 (the fixture's `processedThrough`).
        for month in ((2026, 12), (2027, 1), (2027, 2)):
            ProcessedPayrollPeriod.objects.create(company=cls.company, period=date(*month, 1), processed_on=AS_OF)

    def setUp(self):
        super().setUp()
        self.api = self.client_for(self.admin)

    def post(self, code, suffix, body):
        return self.api.post(url(code, suffix), body, format="json")


class AssignmentTests(SalaryApiTestCase):
    def test_assignment_defaults_to_the_date_of_joining_and_writes_history(self):
        employee = make_employee(self.company, "EMP-0142", doj=date(2027, 3, 1), grade="G5")
        response = self.post("EMP-0142", "/salary", {"template": "std", "amount": "22000"})
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["effectiveFrom"], "2027-03-01")
        self.assertEqual(body["structure"]["gross"], "22000.00")
        self.assertEqual(body["consequence"]["reopenedCount"], 0)
        entry = EmployeeFieldHistory.objects.get(employee=employee, field="salary")
        self.assertEqual((entry.date, entry.from_value), (date(2027, 3, 1), "—"))
        self.assertEqual(entry.to_value, "Gross ৳ 22,000 · Basic ৳ 13,200")
        self.assertEqual(self.post("EMP-0142", "/salary", {"template": "std", "amount": "22000"}).status_code, 409)

    def test_a_joiner_from_before_the_rule_book_can_still_be_assigned(self):
        """The earliest labour set starts 2015-09-01; the structure is checked
        against the floors in force while it is paid, today."""
        make_employee(self.company, "EMP-0010", doj=date(2010, 1, 4), grade="G5")
        response = self.post("EMP-0010", "/salary", {"template": "std", "amount": "22000"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["effectiveFrom"], "2010-01-04")

    def test_the_rmg_default_clears_both_floors_in_every_grade(self):
        """The drafted G1/G2 totals do not reconcile with their basics; the
        default basic rises to the lowest that clears both."""
        book = rule_book(AS_OF)
        for grade in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
            with self.subTest(grade=grade):
                built = build("rmg", None, book, grade=grade)
                self.assertTrue(all(c["passed"] for c in floor_checks(grade, built.basic, built.gross, book)))
        self.assertEqual(build("rmg", None, book, grade="G1").gross, Decimal("15035"))
        make_employee(self.company, "EMP-0153", doj=date(2026, 1, 1), grade="G1")
        self.assertEqual(self.post("EMP-0153", "/salary", {"template": "rmg"}).status_code, 201)

    def test_no_structure_after_the_separation_date(self):
        make_employee(self.company, "EMP-0154", doj=date(2026, 1, 1), separated_on=date(2026, 6, 30),
                      separation_type="RESIGNATION")
        response = self.post("EMP-0154", "/salary", {"template": "std", "amount": "20000",
                                                     "effectiveFrom": "2026-07-01"})
        self.assertEqual(response.status_code, 400)

    def test_a_structure_below_either_floor_is_refused(self):
        make_employee(self.company, "EMP-0150", doj=date(2026, 1, 1), grade="G1")
        response = self.post("EMP-0150", "/salary", {"template": "std", "amount": "12000"})
        self.assertEqual(response.status_code, 400, response.content)
        messages = response.json()["errors"][0]["messages"]
        self.assertEqual(len(messages), 2)
        self.assertIn("Basic ৳ 7,200 is below the gazetted basic floor of ৳ 8,200", messages[0])
        self.assertIn("Total monthly wage ৳ 12,000 is below the gazetted total floor", messages[1])
        self.assertFalse(EmployeeSalaryStructure.objects.filter(employee__code="EMP-0150").exists())

    def test_assigning_into_processed_periods_states_the_arrears(self):
        make_employee(self.company, "EMP-0151", doj=date(2027, 1, 1))
        body = self.post("EMP-0151", "/salary", {"template": "std", "amount": "20000", "preview": True}).json()
        self.assertFalse(body["saved"])
        self.assertEqual(body["consequence"]["reopenedPeriods"], ["2027-01", "2027-02"])
        self.assertEqual(body["consequence"]["arrears"], "40000.00")  # never paid: the full gross, twice

    def test_only_an_admin_of_the_company_may_assign(self):
        make_employee(self.company, "EMP-0152", doj=date(2027, 1, 1))
        response = self.client_for(self.member).post(url("EMP-0152", "/salary"),
                                                     {"template": "std", "amount": "20000"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client_for(self.member).get(url("EMP-0152", "/salary")).status_code, 200)


class RevisionTests(SalaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142", doj=date(2019, 3, 11), grade="G5")
        self.original = salary.assign(self.employee, template="std", amount=Decimal("22000"),
                                      effective_from=date(2026, 7, 1))["structure"]

    def revise(self, **body):
        return self.post("EMP-0142", "/salary/revise", {"method": "PERCENTAGE_INCREASE", "value": "10", **body})

    def test_the_default_is_the_next_unprocessed_period(self):
        """Acceptance test 7, first half: March 2027, not the date of joining."""
        self.assertEqual(self.api.get(url("EMP-0142", "/salary")).json()["revisionDefault"], "2027-03-01")
        body = self.revise(preview=True).json()
        self.assertEqual((body["effectiveFrom"], body["backdated"]), ("2027-03-01", False))
        self.assertEqual(body["consequence"]["reopenedCount"], 0)
        self.assertEqual(body["gross"], "24200.00")

    def test_backdating_without_a_reason_is_refused_and_states_what_it_would_reopen(self):
        """Acceptance test 7, second half."""
        response = self.revise(effectiveFrom="2027-01-01")
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["errors"][0]["path"], "reason")
        self.assertEqual(body["consequence"]["reopenedPeriods"], ["2027-01", "2027-02"])
        self.assertEqual(body["consequence"]["reopenedCount"], 2)
        self.assertEqual(body["consequence"]["arrears"], "4400.00")  # 2,200 a month, twice
        self.assertEqual(EmployeeSalaryStructure.objects.filter(employee=self.employee).count(), 1)
        self.assertEqual(EmployeeFieldHistory.objects.filter(employee=self.employee, field="salary").count(), 1)
        self.assertEqual(self.revise(effectiveFrom="2027-01-01", reason="too short").status_code, 400)

    def test_a_backdated_revision_with_a_reason_closes_the_old_structure(self):
        response = self.revise(effectiveFrom="2027-02-15", reason="Annual increment agreed in January", type="INCREMENT")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["backdated"])
        # February from the 15th: 14 of 28 days at the new rate.
        self.assertEqual(body["consequence"]["periods"][0]["factor"], "0.5000")
        self.assertEqual(body["structure"]["arrears"], "1100.00")
        self.assertEqual(body["structure"]["reopenedPeriods"], ["2027-02"])

        old = EmployeeSalaryStructure.objects.get(uid=self.original["uid"])
        self.assertEqual(old.effective_to, date(2027, 2, 14))
        self.assertEqual(str(old.superseded_by.uid), body["structure"]["uid"])
        # Never overwritten: the old structure still answers for the old dates.
        self.assertEqual(old.gross, Decimal("22000"))
        self.assertEqual(structure_in_force(self.employee, date(2027, 2, 14)).pk, old.pk)
        self.assertEqual(structure_in_force(self.employee, date(2027, 2, 15)).gross, Decimal("24200"))
        entry = EmployeeFieldHistory.objects.filter(employee=self.employee, field="salary").first()
        self.assertEqual((entry.date, entry.reason), (date(2027, 2, 15), "Annual increment agreed in January"))
        self.assertEqual(entry.from_value, "Gross ৳ 22,000 · Basic ৳ 13,200")

        history = self.api.get(url("EMP-0142", "/salary/history")).json()["structures"]
        self.assertEqual([s["gross"] for s in history], ["24200.00", "22000.00"])
        self.assertEqual(history[1]["supersededBy"], history[0]["uid"])

    def test_working_26_arrears_prorate_by_calendar_without_a_holiday_calendar(self):
        """The weekly holidays in a part period are not on file; counting every
        calendar day as a working day lost zeroed January's arrears."""
        CompanyStatutoryProfile.objects.update_or_create(company=self.company,
                                                         defaults={"proration_divisor": "WORKING_26"})
        body = self.revise(effectiveFrom="2027-01-27", reason="Late-January increment", preview=True).json()
        january = body["consequence"]["periods"][0]
        self.assertEqual((january["period"], january["factor"]), ("2027-01", "0.1613"))  # 5 of 31 days
        self.assertEqual(body["consequence"]["prorationDivisor"], "CALENDAR_ACTUAL")

    def test_a_large_increment_warns_but_saves(self):
        response = self.revise(value="30")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([w["key"] for w in response.json()["warnings"]], ["salary.largeIncrement"])

    def test_methods(self):
        self.assertEqual(self.revise(method="FIXED_INCREASE", value="1000", preview=True).json()["gross"], "23000.00")
        self.assertEqual(self.revise(method="NEW_GROSS", value="30000", preview=True).json()["gross"], "30000.00")
        changed = self.revise(method="CHANGE_TEMPLATE", value="classic", preview=True).json()
        self.assertEqual((changed["template"], changed["gross"]), ("classic", "22000.00"))
        rounded = self.revise(value="7", rounding=500, preview=True).json()
        self.assertEqual(rounded["gross"], "23500.00")  # 23,540 to the nearest 500
        self.assertEqual(self.revise(method="NEW_BASIC", value="9000").status_code, 400)
        self.assertEqual(self.revise(value="0").status_code, 400)  # the same structure again
        self.assertEqual(self.revise(value=10.5).status_code, 400)  # a float
        for bad in ("NaN", "sNaN", "Infinity", "1e30", "abc"):
            with self.subTest(value=bad):
                self.assertEqual(self.revise(value=bad).status_code, 400)
        self.assertEqual(self.revise(method="CHANGE_TEMPLATE", template="classic", value="abc").status_code, 400)
        self.assertEqual(self.revise(method="NEW_GROSS", value="1e17").status_code, 400)
        self.assertEqual(self.revise(effectiveFrom="2026-07-01", reason="Correcting the original").status_code, 400)

    def test_compliance_blocks_a_structure_below_its_floor(self):
        """Acceptance test 2, floor half: both floors, on the full monthly rate."""
        below = make_employee(self.company, "EMP-0160", doj=date(2026, 1, 1), grade="G1")
        give_structure(below, 12000)  # basic 7,200 and total 12,000 against 8,200 / 15,035
        result = evaluate(below)
        self.assertEqual([f.key for f in result.blocks], ["salary.belowBasicFloor", "salary.belowTotalFloor"])
        self.assertTrue(all(f.tab == "salary" for f in result.blocks))

        total_only = make_employee(self.company, "EMP-0161", doj=date(2026, 1, 1), grade="G1")
        give_structure(total_only, 14000)  # basic 8,400 clears; total does not
        self.assertEqual([f.key for f in evaluate(total_only).blocks], ["salary.belowTotalFloor"])

        # Joined mid-month at exactly the floor: proration is not underpayment.
        mid_month = make_employee(self.company, "EMP-0162", doj=date(2027, 3, 5), grade="G7")
        salary.assign(mid_month, template="rmg")
        self.assertEqual(evaluate(mid_month).blocks, [])
