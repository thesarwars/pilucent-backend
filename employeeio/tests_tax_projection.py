"""Income tax projection (doc §7.5, §2.5, acceptance test 3).

The critical defect: the engine keys thresholds off taxpayer flags, and a
caller passing only the category string assessed everybody on the GENERAL
threshold -- a woman entitled to Tk 450,000 was taxed from Tk 400,000 and
over-withheld all year. The category now becomes flags in exactly one place.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from employeeio.choices import TaxpayerCategoryChoices as Cat
from employeeio.models import EmployeeInvestment
from employeeio.services.tax import flags_for_category, project, suggest_category
from employeeio.test_support import FrozenClockMixin, give_structure, make_company, make_employee, seed_rules


class TaxProjectionTests(FrozenClockMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")

    def employee(self, code, gross=100000, category=Cat.GENERAL, classification="NON_WORKER", **fields):
        employee = make_employee(self.company, code, classification=classification, **fields)
        employee.tax_profile.category = category
        employee.tax_profile.save()
        give_structure(employee, gross)
        return employee

    def figure(self, projection, key):
        return projection.figures[key].value

    def test_a_worked_general_projection(self):
        """Tk 100,000 a month, non-worker: 1,200,000 income, 400,000 exempt,
        800,000 taxable; 400,000 above the threshold walks 300,000 at 10% and
        100,000 at 15%."""
        p = project(self.employee("EMP-0001"))
        self.assertEqual(self.figure(p, "employmentIncome"), Decimal("1200000"))
        self.assertEqual(self.figure(p, "exemption"), Decimal("400000"))
        self.assertEqual(self.figure(p, "taxable"), Decimal("800000"))
        self.assertEqual(self.figure(p, "threshold"), Decimal("400000"))
        self.assertEqual(self.figure(p, "slabTax"), Decimal("45000"))
        self.assertEqual(p.liability, Decimal("45000"))
        self.assertEqual([b["tax"] for b in p.slab_walk], ["30000.00", "15000.00"])

    def test_a_woman_is_assessed_on_the_450000_threshold(self):
        """Acceptance test 3."""
        woman = project(self.employee("EMP-0002", category=Cat.FEMALE, gender="FEMALE"))
        self.assertEqual(self.figure(woman, "threshold"), Decimal("450000"))
        self.assertEqual(woman.liability, Decimal("37500"))
        self.assertTrue(woman.flags.woman)
        self.assertIn("FEMALE threshold", woman.figures["threshold"].basis)

    def test_the_category_decides_not_the_gender(self):
        """Suggestion is never auto-applied: a woman left on GENERAL is assessed
        on GENERAL, and is offered FEMALE."""
        employee = self.employee("EMP-0003", category=Cat.GENERAL, gender="FEMALE")
        self.assertEqual(self.figure(project(employee), "threshold"), Decimal("400000"))
        self.assertEqual(suggest_category(employee), Cat.FEMALE)

    def test_every_category_translates_to_flags(self):
        expected = {
            Cat.GENERAL: {}, Cat.FEMALE: {"woman": True}, Cat.SENIOR_CITIZEN_65_PLUS: {"age": 65},
            Cat.PERSON_WITH_DISABILITY: {"disabled": True}, Cat.THIRD_GENDER: {"thirdGender": True},
            Cat.WAR_WOUNDED_FREEDOM_FIGHTER: {"gazettedFreedomFighter": True},
            Cat.NON_RESIDENT_FOREIGN: {"nonResident": True},
        }
        for category, set_flags in expected.items():
            with self.subTest(category=category):
                flags = flags_for_category(category).as_dict()
                self.assertEqual({k: v for k, v in flags.items() if v not in (False, None)}, set_flags)

    def test_thresholds_by_category(self):
        cases = {Cat.SENIOR_CITIZEN_65_PLUS: 450000, Cat.PERSON_WITH_DISABILITY: 525000,
                 Cat.THIRD_GENDER: 525000, Cat.WAR_WOUNDED_FREEDOM_FIGHTER: 550000}
        for n, (category, threshold) in enumerate(cases.items(), 10):
            with self.subTest(category=category):
                p = project(self.employee(f"EMP-00{n}", category=category))
                self.assertEqual(self.figure(p, "threshold"), Decimal(threshold))

    def test_disabled_children_add_to_the_threshold(self):
        employee = self.employee("EMP-0020")
        employee.tax_profile.disabled_children = 2
        employee.tax_profile.save()
        self.assertEqual(self.figure(project(employee), "threshold"), Decimal("500000"))

    def test_a_non_resident_foreigner_bypasses_the_slab_walk(self):
        p = project(self.employee("EMP-0021", category=Cat.NON_RESIDENT_FOREIGN, work_permit="WP-1"))
        self.assertEqual(p.slab_walk, [])
        self.assertNotIn("exemption", p.figures)
        self.assertEqual(p.liability, Decimal("360000"))  # 30% of 1,200,000

    def test_the_rebate_counts_only_evidenced_investments(self):
        employee = self.employee("EMP-0022")
        EmployeeInvestment.objects.create(employee=employee, instrument="DPS", amount=Decimal("100000"), proof=False)
        self.assertEqual(self.figure(project(employee), "rebate"), Decimal("0"))
        EmployeeInvestment.objects.create(employee=employee, instrument="SANCHAYAPATRA", amount=Decimal("100000"), proof=True)
        # lowest of 10% of 100,000, 3% of 800,000 and 750,000
        self.assertEqual(self.figure(project(employee), "rebate"), Decimal("10000"))

    def test_the_minimum_tax_floor(self):
        """Taxable just above the threshold: the slab tax is below Tk 5,000."""
        p = project(self.employee("EMP-0023", gross=51000))  # taxable 408,000
        self.assertEqual(self.figure(p, "slabTax"), Decimal("800"))
        self.assertEqual(p.liability, Decimal("5000"))

    def test_nil_below_the_threshold(self):
        p = project(self.employee("EMP-0024", gross=40000))
        self.assertEqual(p.liability, Decimal("0"))

    def test_a_worker_is_projected_two_festival_bonuses_on_basic(self):
        worker = self.employee("EMP-0025", gross=100000, classification="WORKER")
        basic = worker.salary_structures.get().basic
        self.assertEqual(self.figure(project(worker), "bonuses"), basic * 2)

    def test_the_period_deduction_spreads_over_the_remaining_income_year(self):
        """Frozen on 2027-03-08: July to February elapsed, four periods left."""
        p = project(self.employee("EMP-0026"))
        self.assertEqual(self.figure(p, "periodsElapsed"), 8)
        self.assertEqual(self.figure(p, "remainingPeriods"), 4)
        self.assertEqual(self.figure(p, "periodDeduction"), Decimal("11250"))

    def test_the_trace_is_numbered_and_every_figure_is_attributed(self):
        data = project(self.employee("EMP-0027")).as_dict()
        self.assertEqual([s["n"] for s in data["trace"]], list(range(1, len(data["trace"]) + 1)))
        for step in data["trace"]:
            self.assertEqual({"value", "basis", "citation", "confidence"} - step.keys(), set())
            self.assertIsInstance(step["value"], (str, int))
        self.assertEqual(data["threshold"]["citation"], "Finance Act 2026")
        self.assertEqual(data["liability"]["value"], "45000.00")

    def test_a_corroborated_input_marks_the_projection_not_production_safe(self):
        """The festival-bonus count is CORROBORATED in the 2026 labour set."""
        self.assertTrue(project(self.employee("EMP-0028")).as_dict()["productionSafe"])
        self.assertFalse(project(self.employee("EMP-0029", classification="WORKER")).as_dict()["productionSafe"])

    def test_confidence_runs_through_derived_figures(self):
        """The liability cites no rule of its own, but it is computed from the
        CORROBORATED festival-bonus count, so it is not VERIFIED either."""
        worker = project(self.employee("EMP-0031", classification="WORKER")).as_dict()
        self.assertEqual(worker["bonuses"]["confidence"], "CORROBORATED")
        self.assertEqual(worker["liability"]["confidence"], "CORROBORATED")
        self.assertEqual(worker["annualSalary"]["confidence"], "LIVE")
        other = project(self.employee("EMP-0032")).as_dict()
        self.assertEqual(other["liability"]["confidence"], "VERIFIED")

    def test_no_structure_is_not_a_projection(self):
        employee = make_employee(self.company, "EMP-0030")
        p = project(employee)
        self.assertFalse(p.available)
        self.assertIsNone(p.liability)
