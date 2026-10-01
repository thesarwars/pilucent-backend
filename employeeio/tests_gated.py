"""Gated operations (doc §6; acceptance test 8).

A gated change carries an effective date and a reason of at least 10
characters, writes its own history entry, and -- when refused -- still states
the consequence it would have had.
"""

from datetime import date

from django.test import TestCase

from employeeio.models import Employee, EmployeeFieldHistory, ProcessedPayrollPeriod
from employeeio.services import salary
from employeeio.services.compliance import evaluate
from employeeio.test_support import (
    AS_OF,
    ApiMixin,
    give_structure,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
    url,
)


class GatedTestCase(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.admin = make_user(cls.company, "admin@rahman.example")
        make_company_admin(cls.admin, cls.company)
        cls.member = make_user(cls.company, "hr@rahman.example")
        for month in ((2026, 12), (2027, 1), (2027, 2)):
            ProcessedPayrollPeriod.objects.create(company=cls.company, period=date(*month, 1), processed_on=AS_OF)

    def setUp(self):
        super().setUp()
        self.api = self.client_for(self.admin)

    def post(self, code, suffix, body, user=None):
        client = self.client_for(user) if user else self.api
        return client.post(url(code, suffix), body, format="json")


class ClassificationTests(GatedTestCase):
    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142", doj=date(2019, 3, 11), classification="WORKER")
        give_structure(self.employee, 22000)

    def change(self, reason, effective="2027-01-01", user=None):
        return self.post("EMP-0142", "/classification",
                         {"to": "NON_WORKER", "effective": effective, "reason": reason}, user)

    def history(self):
        return EmployeeFieldHistory.objects.filter(employee=self.employee, field="classification")

    def test_nine_characters_is_refused_and_ten_succeeds(self):
        """Acceptance test 8."""
        refused = self.change("Promotion")  # 9 characters
        self.assertEqual(refused.status_code, 400, refused.content)
        body = refused.json()
        self.assertEqual(body["errors"][0]["path"], "reason")
        self.assertIn("(9 so far)", body["errors"][0]["messages"][0])
        # The consequence it would have had: three paid periods, retroactive.
        self.assertEqual(body["consequence"], {"completedPayrollRuns": 3, "retroactive": True})
        self.assertEqual(self.history().count(), 0)
        self.assertEqual(Employee.objects.get(pk=self.employee.pk).classification, "WORKER")

        done = self.change("Promotions")  # 10 characters
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(self.history().count(), 1)
        entry = self.history().get()
        self.assertEqual((entry.date, entry.from_value, entry.to_value, entry.reason),
                         (date(2027, 1, 1), "Worker", "Non-worker", "Promotions"))
        body = done.json()
        self.assertEqual((body["classification"], body["retroactive"], body["completedPayrollRuns"]),
                         ("NON_WORKER", True, 3))
        self.assertEqual(body["history"]["reason"], "Promotions")
        self.assertEqual(Employee.objects.get(pk=self.employee.pk).classification, "NON_WORKER")

    def test_a_future_change_waits_for_its_date(self):
        """Classification is one column: applied early, it would drop this
        year's projected festival bonuses months before the change."""
        refused = self.change("Duties changed to supervision", effective="2027-12-01")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["consequence"]["retroactive"], False)
        self.assertEqual(Employee.objects.get(pk=self.employee.pk).classification, "WORKER")
        today = self.change("Duties changed to supervision", effective="2027-03-08").json()
        self.assertEqual((today["classification"], today["retroactive"]), ("NON_WORKER", False))

    def test_the_employment_tab_points_at_the_gated_operation(self):
        response = self.api.patch(url("EMP-0142", "/employment"), {"classification": "NON_WORKER"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("POST /employees/EMP-0142/classification", str(response.json()))

    def test_only_an_admin_of_the_company(self):
        self.assertEqual(self.change("Duties changed to supervision", user=self.member).status_code, 403)

    def test_completed_runs_count_only_periods_with_pay(self):
        new = make_employee(self.company, "EMP-0150", doj=date(2027, 1, 20))
        self.assertEqual(new.completed_payroll_runs, 0)  # no structure: blocked from every run
        salary.assign(new, template="std", amount=20000)
        self.assertEqual(new.completed_payroll_runs, 2)  # January and February


class SeparationTests(GatedTestCase):
    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142", doj=date(2021, 3, 8))
        give_structure(self.employee, 50000)  # basic 30,000

    def separate(self, **body):
        return self.post("EMP-0142", "/separation",
                         {"type": "TERMINATION", "date": "2027-03-08", "reason": "Position made redundant", **body})

    def test_a_preview_states_the_entitlement_and_records_nothing(self):
        body = self.separate(preview=True).json()
        self.assertEqual((body["years"], body["daysPerYear"], body["payable"]["value"]), (6, 30, "180000.00"))
        self.assertIsNone(Employee.objects.get(pk=self.employee.pk).separated_on)

    def test_separation_records_the_date_blocks_payroll_and_writes_history(self):
        refused = self.separate(reason="Redundant")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["consequence"]["entitlement"]["payable"]["value"], "180000.00")

        response = self.separate()
        self.assertEqual(response.status_code, 201, response.content)
        employee = Employee.objects.get(pk=self.employee.pk)
        self.assertEqual((employee.separated_on, employee.separation_type), (date(2027, 3, 8), "TERMINATION"))
        self.assertIn("salary.settlementOutstanding", [f.key for f in evaluate(employee).blocks])
        entry = EmployeeFieldHistory.objects.get(employee=employee, field="separation")
        self.assertEqual((entry.to_value, entry.reason), ("Termination", "Position made redundant"))
        self.assertEqual(self.separate().status_code, 409)

    def test_a_separation_blocks_payroll_only_from_its_date(self):
        """Someone working out their notice is still paid."""
        self.assertEqual(self.separate(date="2027-05-31").status_code, 201)
        employee = Employee.objects.get(pk=self.employee.pk)
        self.assertNotIn("salary.settlementOutstanding", [f.key for f in evaluate(employee).blocks])
        self.assertIn("salary.settlementOutstanding",
                      [f.key for f in evaluate(employee, as_of=date(2027, 5, 31)).blocks])

    def test_a_retirement_before_the_amendment_can_be_recorded(self):
        """The 2015 labour set has no retirement age to warn against."""
        response = self.separate(type="RETIREMENT", date="2026-03-31")
        self.assertEqual(response.status_code, 201, response.content)

    def test_gross_misconduct_is_a_dismissal_only(self):
        self.assertEqual(self.separate(grossMisconduct=True).status_code, 400)
        body = self.separate(type="DISMISSAL", grossMisconduct=True, preview=True).json()
        self.assertEqual(body["payable"]["value"], "0.00")

    def test_only_an_admin_of_the_company(self):
        response = self.client_for(self.member).post(
            url("EMP-0142", "/separation"),
            {"type": "TERMINATION", "date": "2027-03-08", "reason": "Position made redundant"}, format="json")
        self.assertEqual(response.status_code, 403)
