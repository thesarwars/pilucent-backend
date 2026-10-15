"""Salary structures (employee profile §5-§6.2; salary profile backend §4-§8,
golden vectors §12).

The floors are the rule book's gazetted RMG floors, not the salary spec's
seed table: one source for one statutory number. The spec's G2/G3 (a worker
at 25,000 below a 14,000 grade-5 floor) are restated against them.
"""

import json
from datetime import date
from decimal import Decimal

from django.test import TestCase

from employeeio.models import (
    CompanyStatutoryProfile,
    EmployeeFieldHistory,
    EmployeeSalaryComponent,
    EmployeeSalaryStructure,
    ProcessedPayrollPeriod,
    SalaryAudit,
    SalaryOverride,
)
from employeeio.services import salary
from employeeio.services.compliance import evaluate
from employeeio.services.salary import (
    Built,
    Intent,
    SalaryRefused,
    build,
    floor_checks,
    structure_in_force,
    structure_out,
    warnings_for,
)
from employeeio.services.salary_templates import ComponentsExceedGross, Split, build_split, pct, templates_on
from employeeio.test_support import (
    AS_OF,
    ApiMixin,
    FrozenClockMixin,
    give_salary_permissions,
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
        cls.company = make_company("Rahman Garments")

    def setUp(self):
        super().setUp()
        self.book = rule_book(AS_OF)

    def build(self, template, amount, **kw):
        return build(template, Decimal(amount), self.book, company=self.company, on=AS_OF, **kw)

    def test_seeded_templates_and_management_is_left_out(self):
        rows = templates_on(self.company, AS_OF)
        self.assertEqual([r.code for r in rows], ["officer", "worker", "staff"])
        self.assertEqual([Split.of(r).notation for r in rows], ["60 / 50 / 6 / 4", "55 / 50 / 8 / 5", "58 / 50 / 7 / 5"])
        self.assertEqual([Split.of(r).remainder for r in rows], [Decimal("0"), Decimal("4.5"), Decimal("1")])

    def test_g1_officer_at_46000(self):
        self.assertEqual(amounts(self.build("officer", "46000")),
                         {"BASIC": 27600, "HRA": 13800, "MED": 2760, "CONV": 1840})

    def test_g2_g3_worker_basic_holds_at_55_and_other_takes_the_rest(self):
        built = self.build("worker", "25000")
        self.assertEqual(amounts(built), {"BASIC": 13750, "HRA": 6875, "MED": 2000, "CONV": 1250, "OTHER": 1125})
        self.assertEqual(built.gross, Decimal("25000"))
        self.assertEqual(self.build("worker", "25500").basic, Decimal("14025"))
        lines = {r["code"]: r for r in salary.describe(built)}
        self.assertEqual(lines["OTHER"]["basis_text"], "Balance of gross")
        self.assertTrue(lines["OTHER"]["is_balancing"])
        self.assertFalse(any(r["is_overridden"] for r in lines.values()))

    def test_g4_every_template_sums_to_gross(self):
        """1,000 to 200,000; every taka to 20,000, then every 7th."""
        splits = [Split.of(r) for r in templates_on(self.company, AS_OF)]
        grosses = list(range(1000, 20001)) + list(range(20001, 200001, 7))
        for split in splits:
            for gross in grosses:
                lines = build_split(split, Decimal(gross))
                if sum(a for _, a in lines) != gross:
                    self.fail(f"{split.notation} at {gross}: {lines}")

    def test_split_of_a_fresh_build_returns_the_templates_percentages(self):
        for row in templates_on(self.company, AS_OF):
            split = Split.of(row)
            for gross in (12345, 46000, 187654):
                lines = dict(build_split(split, Decimal(gross)))
                self.assertLessEqual(abs(pct(lines["BASIC"], gross) - split.basic), Decimal("0.1"))
                self.assertLessEqual(abs(pct(lines["HRA"], lines["BASIC"]) - split.hr), Decimal("0.1"))

    def test_an_override_is_measured_and_other_absorbs_it(self):
        built = self.build("officer", "46000", overrides={"CONV": Intent("FIXED", Decimal("1000"), "Field role")})
        self.assertEqual(amounts(built), {"BASIC": 27600, "HRA": 13800, "MED": 2760, "CONV": 1000, "OTHER": 840})
        lines = {r["code"]: r for r in salary.describe(built)}
        self.assertTrue(lines["CONV"]["is_overridden"])  # 2.2% against the template's 4%
        self.assertFalse(lines["BASIC"]["is_overridden"])
        self.assertTrue(lines["OTHER"]["is_balancing"])

    def test_lines_that_exceed_gross_are_refused(self):
        split = Split.of(templates_on(self.company, AS_OF)[0])
        with self.assertRaises(ComponentsExceedGross):
            build_split(split, Decimal("46000"), {"CONV": ("FIXED", Decimal("3000"))})

    def test_retired_templates_cannot_build(self):
        with self.assertRaises(SalaryRefused):
            self.build("std", "22000")

    def test_rmg_builds_up_from_the_gazetted_basic(self):
        """With no amount, basic is the grade's gazetted basic, and the
        gazetted allowances bring it to exactly the grade's total floor."""
        built = build("rmg", None, self.book, grade="G7")
        self.assertEqual(amounts(built), {"BASIC": 6700, "HRA": 3350, "MED": 750, "CONV": 450, "FOOD": 1250})
        self.assertEqual(built.gross, Decimal("12500"))
        self.assertTrue(all(c["passed"] for c in floor_checks("G7", built.basic, built.gross, self.book)))

    def test_effective_percentages_are_back_solved_never_the_templates(self):
        """§5.1: 58.6% of gross when that is what is on file."""
        employee = make_employee(self.company, "EMP-0142")
        structure = EmployeeSalaryStructure.objects.create(employee=employee, effective_from=date(2026, 7, 1),
                                                           template="std")
        for position, (code, amount) in enumerate([("BASIC", 12892), ("HRA", 6908), ("MED", 1540), ("CONV", 660)]):
            EmployeeSalaryComponent.objects.create(structure=structure, code=code, amount=amount, position=position)
        out = structure_out(structure)
        self.assertEqual(out["basicPercentOfGross"], "58.6")
        self.assertEqual(out["components"][0]["basis"], "58.6% of gross")
        self.assertTrue(out["templateRetired"])
        self.assertEqual(out["grossInWords"]["en"], "Twenty two thousand taka only")

    def test_both_floors_with_separate_messages(self):
        """A structure can clear the basic floor and fail the total."""
        built = self.build("officer", "14000")  # basic 8,400
        checks = {c["kind"]: c for c in floor_checks("G1", built.basic, built.gross, self.book)}
        self.assertTrue(checks["basic"]["passed"])
        self.assertFalse(checks["total"]["passed"])
        self.assertIn("below the gazetted total floor of ৳ 15,035 for Grade 1", checks["total"]["message"])
        self.assertIn("s.289(1)", checks["total"]["message"])
        self.assertEqual(checks["total"]["confidence"], "DRAFTED")

    def test_warnings_never_block(self):
        low = Built("custom", [("BASIC", Decimal("9000")), ("HRA", Decimal("11000"))])
        self.assertEqual([w["key"] for w in warnings_for(low, current_gross=Decimal("15000"))],
                         ["salary.largeIncrement", "salary.lowBasicShare"])
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
        # Processed through February 2027.
        for month in ((2026, 12), (2027, 1), (2027, 2)):
            ProcessedPayrollPeriod.objects.create(company=cls.company, period=date(*month, 1), processed_on=AS_OF)

    def setUp(self):
        super().setUp()
        self.api = self.client_for(self.admin)

    def write(self, code, body, client=None, **headers):
        return (client or self.api).post(url(code, "/salary-structures"), body, format="json", **headers)

    def latest_uid(self, code):
        return self.api.get(url(code, "/salary-structures")).json()["latest"]


class AssignmentTests(SalaryApiTestCase):
    def test_assignment_defaults_to_the_date_of_joining_and_writes_history_and_audit(self):
        employee = make_employee(self.company, "EMP-0142", doj=date(2027, 3, 1), grade="G5")
        response = self.write("EMP-0142", {"templateCode": "officer", "gross": "22000"})
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["effectiveFrom"], "2027-03-01")
        self.assertEqual(body["structure"]["gross"], "22000.00")
        self.assertEqual(body["structure"]["revisionType"], "FIRST_ASSIGNMENT")
        self.assertEqual(body["structure"]["approvedBy"], "Admin")
        self.assertTrue(body["structure"]["ruleSet"])
        entry = EmployeeFieldHistory.objects.get(employee=employee, field="salary")
        self.assertEqual((entry.date, entry.from_value), (date(2027, 3, 1), "—"))
        self.assertEqual(entry.to_value, "Gross ৳ 22,000 · Basic ৳ 13,200")
        self.assertEqual(list(SalaryAudit.objects.filter(employee=employee).values_list("action", flat=True)),
                         ["ASSIGNED"])
        # A second write must name the structure it is based on.
        again = self.write("EMP-0142", {"templateCode": "officer", "gross": "23000"})
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.json()["errors"][0]["path"], "expectedStructure")

    def test_a_joiner_from_before_the_rule_book_can_still_be_assigned(self):
        make_employee(self.company, "EMP-0010", doj=date(2010, 1, 4), grade="G5")
        response = self.write("EMP-0010", {"templateCode": "officer", "gross": "22000"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["effectiveFrom"], "2010-01-04")

    def test_the_rmg_default_clears_both_floors_in_every_grade(self):
        book = rule_book(AS_OF)
        for grade in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
            with self.subTest(grade=grade):
                built = build("rmg", None, book, grade=grade)
                self.assertTrue(all(c["passed"] for c in floor_checks(grade, built.basic, built.gross, book)))
        make_employee(self.company, "EMP-0153", doj=date(2026, 1, 1), grade="G1")
        self.assertEqual(self.write("EMP-0153", {"templateCode": "rmg"}).status_code, 201)

    def test_retired_templates_are_not_offered(self):
        make_employee(self.company, "EMP-0155", doj=date(2026, 1, 1))
        self.assertEqual(self.write("EMP-0155", {"templateCode": "std", "gross": "22000"}).status_code, 400)

    def test_no_structure_after_the_separation_date(self):
        make_employee(self.company, "EMP-0154", doj=date(2026, 1, 1), separated_on=date(2026, 6, 30),
                      separation_type="RESIGNATION")
        response = self.write("EMP-0154", {"templateCode": "officer", "gross": "20000", "effectiveFrom": "2026-07-01"})
        self.assertEqual(response.status_code, 400)

    def test_below_either_floor_is_refused_with_the_gross_that_clears_it(self):
        make_employee(self.company, "EMP-0150", doj=date(2026, 1, 1), grade="G1")
        response = self.write("EMP-0150", {"templateCode": "officer", "gross": "12000"})
        self.assertEqual(response.status_code, 422, response.content)
        body = response.json()
        messages = body["errors"][0]["messages"]
        self.assertIn("Basic ৳ 7,200 is below the gazetted basic floor of ৳ 8,200", messages[0])
        self.assertIn("Total monthly wage ৳ 12,000 is below the gazetted total floor", messages[1])
        self.assertEqual(body["consequence"]["requiredGross"], "15035.00")
        self.assertFalse(EmployeeSalaryStructure.objects.filter(employee__code="EMP-0150").exists())
        self.assertEqual(self.write("EMP-0150", {"templateCode": "officer", "gross": "15035"}).status_code, 201)

    def test_assigning_into_processed_periods_states_the_arrears(self):
        make_employee(self.company, "EMP-0151", doj=date(2027, 1, 1))
        body = self.write("EMP-0151", {"templateCode": "officer", "gross": "20000", "preview": True}).json()
        self.assertFalse(body["saved"])
        self.assertEqual(body["consequence"]["reopenedPeriods"], ["2027-01", "2027-02"])
        self.assertEqual(body["consequence"]["arrears"], "40000.00")
        self.assertEqual([r["key"] for r in body["employerCost"]["rows"]],
                         ["gross", "providentFund", "gratuity", "festivalBonus", "insurance"])

    def test_writing_needs_the_write_permission(self):
        make_employee(self.company, "EMP-0152", doj=date(2027, 1, 1))
        response = self.write("EMP-0152", {"templateCode": "officer", "gross": "20000"},
                              client=self.client_for(self.member))
        self.assertEqual(response.status_code, 403)
        give_salary_permissions(self.member, self.company, "write_salary")
        response = self.write("EMP-0152", {"templateCode": "officer", "gross": "20000"},
                              client=self.client_for(self.member))
        self.assertEqual(response.status_code, 403)  # a save's preview states the figures
        give_salary_permissions(self.member, self.company, "view_salary_figures")
        response = self.write("EMP-0152", {"templateCode": "officer", "gross": "20000"},
                              client=self.client_for(self.member))
        self.assertEqual(response.status_code, 201, response.content)

    def test_the_old_write_endpoints_are_gone(self):
        make_employee(self.company, "EMP-0156", doj=date(2027, 1, 1))
        self.assertEqual(self.api.post(url("EMP-0156", "/salary"), {"template": "officer", "amount": "20000"},
                                       format="json").status_code, 405)

    def test_idempotency_key_replays_the_original(self):
        employee = make_employee(self.company, "EMP-0157", doj=date(2027, 3, 1))
        first = self.write("EMP-0157", {"templateCode": "officer", "gross": "22000"}, HTTP_IDEMPOTENCY_KEY="abc-1")
        second = self.write("EMP-0157", {"templateCode": "officer", "gross": "22000"}, HTTP_IDEMPOTENCY_KEY="abc-1")
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(first.json()["structure"]["uid"], second.json()["structure"]["uid"])
        self.assertEqual(EmployeeSalaryStructure.objects.filter(employee=employee).count(), 1)


class RevisionTests(SalaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142", doj=date(2019, 3, 11), grade="G5")
        self.original = salary.assign(self.employee, template="officer", amount=Decimal("22000"),
                                      effective_from=date(2026, 7, 1))["structure"]

    def revise(self, **body):
        body = {"method": "PERCENTAGE_INCREASE", "value": "10", "expectedStructure": self.latest_uid("EMP-0142"),
                **body}
        return self.write("EMP-0142", body)

    def test_g8_the_default_is_the_next_unprocessed_period(self):
        """March 2027, never the date of joining."""
        body = self.api.get(url("EMP-0142", "/salary-structures")).json()
        self.assertEqual(body["defaults"]["revision"], "2027-03-01")
        self.assertEqual(body["defaults"]["nextPeriodStart"], "2027-03-01")
        preview = self.revise(preview=True).json()
        self.assertEqual((preview["effectiveFrom"], preview["backdated"]), ("2027-03-01", False))
        self.assertEqual(preview["gross"], "24200.00")
        reassigned = self.write("EMP-0142", {"templateCode": "worker", "gross": "26000", "preview": True,
                                             "expectedStructure": self.original["uid"]}).json()
        self.assertEqual(reassigned["effectiveFrom"], "2027-03-01")

    def test_g7_backdating_needs_a_reason_and_states_what_it_reopens(self):
        response = self.revise(effectiveFrom="2027-01-01")
        self.assertEqual(response.status_code, 422, response.content)
        body = response.json()
        self.assertEqual(body["errors"][0]["path"], "reason")
        self.assertEqual(body["consequence"]["reopenedPeriods"], ["2027-01", "2027-02"])
        self.assertEqual(body["consequence"]["arrears"], "4400.00")
        self.assertEqual(EmployeeSalaryStructure.objects.filter(employee=self.employee).count(), 1)
        self.assertEqual(self.revise(effectiveFrom="2027-01-01", reason="too short").status_code, 422)

        response = self.revise(effectiveFrom="2027-02-15", reason="Annual increment agreed in January",
                               revisionType="INCREMENT")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["backdated"])
        self.assertEqual(body["consequence"]["periods"][0]["factor"], "0.5000")
        self.assertEqual(body["structure"]["arrears"], "1100.00")
        self.assertEqual(body["structure"]["arrearsFrom"], "2027-02")
        old = EmployeeSalaryStructure.objects.get(uid=self.original["uid"])
        self.assertEqual(old.effective_to, date(2027, 2, 14))
        self.assertEqual(old.gross, Decimal("22000"))  # never overwritten
        self.assertEqual(structure_in_force(self.employee, date(2027, 2, 14)).pk, old.pk)
        self.assertIn("SUPERSEDED", SalaryAudit.objects.filter(employee=self.employee).values_list("action", flat=True))

    def test_g10_a_stale_revision_is_refused(self):
        stale = self.original["uid"]
        self.assertEqual(self.revise(expectedStructure=stale).status_code, 201)
        response = self.revise(expectedStructure=stale, value="5")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["errors"][0]["path"], "expectedStructure")

    def test_working_26_arrears_prorate_by_calendar_without_a_holiday_calendar(self):
        CompanyStatutoryProfile.objects.update_or_create(company=self.company,
                                                         defaults={"proration_divisor": "WORKING_26"})
        body = self.revise(effectiveFrom="2027-01-27", reason="Late-January increment", preview=True).json()
        january = body["consequence"]["periods"][0]
        self.assertEqual((january["period"], january["factor"]), ("2027-01", "0.1613"))
        self.assertEqual(body["consequence"]["prorationDivisor"], "CALENDAR_ACTUAL")

    def test_methods(self):
        self.assertEqual(self.revise(method="FIXED_INCREASE", value="1000", preview=True).json()["gross"], "23000.00")
        self.assertEqual(self.revise(method="NEW_GROSS", value="30000", preview=True).json()["gross"], "30000.00")
        changed = self.revise(method="CHANGE_TEMPLATE", templateCode="worker", value=None, preview=True).json()
        self.assertEqual((changed["template"], changed["gross"]), ("worker", "22000.00"))
        rounded = self.revise(value="7", rounding=500, preview=True).json()
        self.assertEqual(rounded["gross"], "23500.00")
        self.assertEqual(self.revise(method="NEW_BASIC", value="9000").status_code, 400)
        self.assertEqual(self.revise(value="0").status_code, 400)
        self.assertEqual(self.revise(value=10.5).status_code, 400)
        for bad in ("NaN", "sNaN", "Infinity", "1e30", "abc"):
            with self.subTest(value=bad):
                self.assertEqual(self.revise(value=bad).status_code, 400)
        self.assertEqual(self.revise(effectiveFrom="2026-07-01", reason="Correcting the original").status_code, 400)

    def test_the_gratuity_consequence_is_stated(self):
        body = self.revise(preview=True).json()
        self.assertIn("for all 8 completed years", body["gratuity"]["note"])  # 7y 11m 25d rounds up

    def test_g9_an_override_survives_a_revision(self):
        current = EmployeeSalaryStructure.objects.get(uid=self.original["uid"])
        response = self.api.post(f"/api/v1/we/salary-structures/{current.uid}/overrides", {
            "rows": [{"code": "CONV", "basis": "FIXED", "value": "500"}],
            "reason": "Lives on the factory compound",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        overridden = response.json()["structure"]
        lines = {c["code"]: c for c in overridden["components"]}
        self.assertEqual(lines["CONV"]["amount"], "500.00")
        self.assertTrue(lines["CONV"]["isOverridden"])
        self.assertEqual(lines["CONV"]["templateBasis"], "Template: 4% of gross")
        self.assertEqual(lines["OTHER"]["amount"], "380.00")  # 880 of conveyance → 500, Other takes 380
        self.assertEqual(overridden["effectiveFrom"], "2027-03-01")
        self.assertEqual(overridden["overrideCount"], 2)  # conveyance, and the Other line it created

        revised = self.write("EMP-0142", {"method": "PERCENTAGE_INCREASE", "value": "10",
                                          "expectedStructure": overridden["uid"],
                                          "effectiveFrom": "2027-04-01"})
        self.assertEqual(revised.status_code, 201, revised.content)
        lines = {c["code"]: c for c in revised.json()["structure"]["components"]}
        self.assertEqual(lines["CONV"]["amount"], "500.00")  # still fixed
        self.assertTrue(lines["CONV"]["isOverridden"])
        self.assertEqual(SalaryOverride.objects.filter(structure__uid=revised.json()["structure"]["uid"]).count(), 1)

    def test_an_override_needs_a_reason_and_the_latest_structure(self):
        current = EmployeeSalaryStructure.objects.get(uid=self.original["uid"])
        path = f"/api/v1/we/salary-structures/{current.uid}/overrides"
        rows = [{"code": "MED", "basis": "PCT_GROSS", "value": "4"}]
        self.assertEqual(self.api.post(path, {"rows": rows}, format="json").status_code, 400)
        self.assertEqual(self.api.post(path, {"rows": rows, "preview": True}, format="json").status_code, 200)
        self.assertEqual(self.api.post(path, {"rows": rows, "reason": "Medical cover moved in-house"},
                                       format="json").status_code, 201)
        stale = self.api.post(path, {"rows": rows, "reason": "Medical cover moved in-house"}, format="json")
        self.assertEqual(stale.status_code, 409)

    def test_a_scheduled_change_can_be_cancelled_and_reopens_the_one_it_closed(self):
        response = self.revise(effectiveFrom="2027-06-01", revisionType="INCREMENT")
        self.assertEqual(response.status_code, 201, response.content)
        scheduled = response.json()["structure"]
        self.assertEqual(scheduled["status"], "SCHEDULED")
        profile = self.api.get(url("EMP-0142", "/salary-structures")).json()
        self.assertEqual(profile["structure"]["uid"], self.original["uid"])
        self.assertEqual(profile["scheduled"]["uid"], scheduled["uid"])
        self.assertEqual(profile["scheduledDelta"]["pct"], "10")

        path = f"/api/v1/we/salary-structures/{scheduled['uid']}/cancel"
        self.assertEqual(self.api.post(path, {"reason": "no"}, format="json").status_code, 400)
        response = self.api.post(path, {"reason": "Budget freeze until July"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["cancelled"]["status"], "CANCELLED")
        self.assertIsNone(EmployeeSalaryStructure.objects.get(uid=self.original["uid"]).effective_to)
        self.assertEqual(salary.latest_structure(self.employee).uid.hex, self.original["uid"].replace("-", ""))
        # An in-force structure cannot be cancelled.
        path = f"/api/v1/we/salary-structures/{self.original['uid']}/cancel"
        self.assertEqual(self.api.post(path, {"reason": "Budget freeze until July"}, format="json").status_code, 409)

    def test_history_types_and_floor_then(self):
        self.revise(revisionType="INCREMENT")
        rows = self.api.get(url("EMP-0142", "/salary-history")).json()["structures"]
        self.assertEqual([r["typeLabel"] for r in rows], ["Increment", "First assignment"])
        self.assertEqual(rows[0]["deltaPct"], "10")
        self.assertTrue(rows[1]["floorThen"]["clears"])

    def test_compliance_blocks_a_structure_below_its_floor(self):
        below = make_employee(self.company, "EMP-0160", doj=date(2026, 1, 1), grade="G1")
        give_structure(below, 12000)
        self.assertEqual([f.key for f in evaluate(below).blocks], ["salary.belowBasicFloor", "salary.belowTotalFloor"])
        mid_month = make_employee(self.company, "EMP-0162", doj=date(2027, 3, 5), grade="G7")
        salary.assign(mid_month, template="rmg")
        self.assertEqual(evaluate(mid_month).blocks, [])


class TenureTests(SalaryApiTestCase):
    def test_g5_g6_tenure_rounds_up_past_six_months(self):
        """6y 6m 20d counts as 7 years; 9y 11m as 10 (both over six months).
        The days per year follow the rule book's breakpoint."""
        for doj, years in ((date(2020, 8, 16), 7), (date(2017, 3, 30), 10), (date(2020, 9, 9), 6)):
            employee = make_employee(self.company, f"EMP-T{years}{doj.month}", doj=doj, grade="G5")
            salary.assign(employee, template="officer", amount=Decimal("30000"), effective_from=doj)
            cost = self.api.get(url(employee.code, "/salary-structures")).json()["employerCost"]
            with self.subTest(doj=doj):
                self.assertEqual(cost["tenure"]["years"], years)
                gratuity = next(r for r in cost["rows"] if r["key"] == "gratuity")
                self.assertIn(f"{cost['tenure']['daysPerYear']} days ÷ 12", gratuity["basis"])


class MaskingTests(SalaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142", doj=date(2019, 3, 11), grade="G5")
        salary.assign(self.employee, template="officer", amount=Decimal("23456"), effective_from=date(2026, 7, 1))
        self.member_api = self.client_for(self.member)

    def assert_no_amounts(self, response):
        text = json.dumps(response.json())
        for figure in ("23456", "23,456", "14074", "14,074"):  # gross, basic
            self.assertNotIn(figure, text, response.request["PATH_INFO"])

    def test_a_masked_response_never_contains_an_amount(self):
        for path in (url("EMP-0142", "/salary-structures"), url("EMP-0142", "/salary-history"),
                     url("EMP-0142", "/salary"), url("EMP-0142", "/salary/history"), url("EMP-0142"), url(),
                     "/api/v1/we/salary-profiles", url("EMP-0142", "/compliance"), url("EMP-0142", "/history"),
                     url("EMP-0142", "/tax-projection")):
            with self.subTest(path=path):
                response = self.member_api.get(path)
                self.assertEqual(response.status_code, 200, response.content)
                self.assert_no_amounts(response)
        body = self.member_api.get(url("EMP-0142", "/salary-structures")).json()
        self.assertTrue(body["masked"])
        self.assertEqual(body["structure"]["template"], "officer")
        self.assertTrue(body["floor"]["clears"])

    def test_viewing_is_audited_both_ways(self):
        self.member_api.get(url("EMP-0142", "/salary-structures"))
        self.api.get(url("EMP-0142", "/salary-structures"))
        actions = list(SalaryAudit.objects.filter(employee=self.employee, action__startswith="VIEWED")
                       .order_by("created_at").values_list("action", "actor_role"))
        self.assertEqual(actions, [("VIEWED_MASKED", "member"), ("VIEWED_FULL", "company admin")])

    def test_the_view_permission_unmasks(self):
        give_salary_permissions(self.member, self.company, "view_salary_figures")
        body = self.member_api.get(url("EMP-0142", "/salary-structures")).json()
        self.assertFalse(body["masked"])
        self.assertEqual(body["structure"]["gross"], "23456.00")


class SalaryListTests(SalaryApiTestCase):
    def test_stats_counts_and_filters(self):
        a = make_employee(self.company, "EMP-0001", name_en="Rafiq", doj=date(2026, 1, 1), grade="G1")
        salary.assign(a, template="officer", amount=Decimal("30000"), effective_from=date(2026, 1, 1))
        b = make_employee(self.company, "EMP-0002", name_en="Nasrin", doj=date(2026, 1, 1), grade="G1")
        give_structure(b, 12000)  # below both floors, on file from before
        make_employee(self.company, "EMP-0003", name_en="Karim", doj=date(2026, 1, 1))
        body = self.api.get("/api/v1/we/salary-profiles").json()
        self.assertEqual(body["counts"], {"ALL": 3, "ASSIGNED": 2, "NONE": 1, "FLOOR": 1, "OVERRIDE": 0})
        self.assertEqual(body["stats"]["monthlyGrossTotal"], "42000.00")
        below = self.api.get("/api/v1/we/salary-profiles?filter=FLOOR").json()["results"]
        self.assertEqual([r["code"] for r in below], ["EMP-0002"])
        found = self.api.get("/api/v1/we/salary-profiles?q=officer").json()["results"]
        self.assertEqual([r["code"] for r in found], ["EMP-0001"])
        self.assertEqual(found[0]["basic"], "18000.00")
