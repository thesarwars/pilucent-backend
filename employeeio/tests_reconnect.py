"""Code outside employeeio that reads the BD employee, after the reconnect.

Each of these read a removed US field and either raised on every call or
answered wrongly without raising: the HR dashboard cards (confirmation_date,
date_of_birth, contract_end_date), the onboarding admin's code edit, the US
spreadsheet importer, and model `__str__` for an employee without a login.
docs/employee-reconnect-backlog.md, "Phase 1 reconnect log".

The dashboard helpers take today from `date.today()` (not the BD clock), so
dates here are relative to the real date.
"""

from datetime import date, timedelta

from django.test import TestCase

from accounts.django_rest.serializers.user_onboards import UserOnBoardEditDetailsSerializer
from accounts.models import User
from companyio.models import CompanyUser
from datamigrationio.django_rest.handlers.employees import EmployeesMigrationHandler
from employeeio.test_support import ApiMixin, make_company, make_employee, make_user
from payrollio.models import PayrollSalaryProcess
from weapi.django_rest.helpers.dashboard import hr


class FakeRequest:
    def __init__(self, user):
        self.user = user


class HrDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Rahman Garments")

    def setUp(self):
        self.today = date.today()

    def days(self, n):
        return self.today + timedelta(days=n)

    def test_upcoming_confirmations_are_probationers_ending_in_the_window(self):
        """A future `confirmation` date is a data error the BD contract blocks
        payroll on, not an upcoming confirmation."""
        make_employee(self.company, "EMP-0001", probation_end=self.days(10))
        make_employee(self.company, "EMP-0002", probation_end=self.days(10), confirmation=self.days(-1))
        make_employee(self.company, "EMP-0003", probation_end=self.days(90))
        make_employee(self.company, "EMP-0004", confirmation=self.days(10))
        make_employee(self.company, "EMP-0005", probation_end=self.days(10), separated_on=self.days(-2))
        self.assertEqual(hr.employee_stats(self.company, today=self.today)["upcoming_confirmations"], 1)
        overview = hr.employee_overview(self.company, self.days(-30), self.today)
        self.assertEqual(overview["upcoming_confirmations"], 1)

    def test_joiners_count_from_the_date_of_joining(self):
        make_employee(self.company, "EMP-0001", doj=self.today)
        make_employee(self.company, "EMP-0002", doj=self.days(-400))
        stats = hr.employee_stats(self.company, today=self.today)
        self.assertEqual((stats["net_change"], stats["total_active"]), (1, 2))
        self.assertEqual(hr.employee_overview(self.company, self.days(-1), self.today)["new_joiners"], 1)

    def test_upcoming_events_read_bd_fields_and_need_a_full_year_for_an_anniversary(self):
        # Leap-year offsets, so a window crossing Feb 29 still builds valid dates.
        make_employee(self.company, "EMP-0001", name_en="Veteran",
                      doj=self.days(5).replace(year=self.days(5).year - 4))
        make_employee(self.company, "EMP-0002", name_en="New Hire", doj=self.days(5))
        make_employee(self.company, "EMP-0003", name_en="Birthday", dob=self.days(3).replace(year=1992))
        make_employee(self.company, "EMP-0004", name_en="Contractor", contract_end=self.days(7))
        events = {(e["type"], e["name"]) for e in hr.upcoming_events(self.company, days=30)}
        self.assertIn(("work_anniversary", "Veteran"), events)
        self.assertNotIn(("work_anniversary", "New Hire"), events)
        self.assertIn(("birthday", "Birthday"), events)
        self.assertIn(("contract_end", "Contractor"), events)


class OnboardingCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Rahman Garments")
        cls.user = make_user(cls.company, "worker@example.com")
        make_employee(cls.company, "EMP-0142", user=cls.user)

    def serializer(self, code, editor=None):
        context = {"request": FakeRequest(editor)} if editor else {}
        return UserOnBoardEditDetailsSerializer(
            instance=self.user, data={"employee_code": code}, partial=True, context=context
        )

    def test_a_user_in_two_companies_is_checked_against_the_editors_company(self):
        """The endpoint shows the employee in the editor's active company, so
        that is the code that must not change -- not the other company's.

        The editor's company holds the code that sorts LATER (EMP-0142 after
        EMP-0007), so an unscoped first-by-code lookup would pick the wrong one.
        """
        other = make_company("Beta Textiles")
        CompanyUser.objects.create(user=self.user, company=other)
        make_employee(other, "EMP-0007", user=self.user)
        editor = make_user(self.company, "admin@rahman.example")
        self.assertTrue(self.serializer("EMP-0142", editor).is_valid())
        self.assertFalse(self.serializer("EMP-0007", editor).is_valid())

    def test_a_different_code_is_refused_before_anything_is_saved(self):
        serializer = self.serializer("EMP-9999", self.editor())
        self.assertFalse(serializer.is_valid())
        self.assertIn("never reassigned", str(serializer.errors["employee_code"]))

    def test_the_same_code_is_accepted(self):
        serializer = self.serializer("EMP-0142", self.editor())
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def editor(self):
        """An admin of the company whose employee is being edited (the endpoint
        always passes the request; its active company is what is compared)."""
        return make_user(self.company, "hr@rahman.example")


class OnboardingListScopeTests(ApiMixin, TestCase):
    """The onboarding list and detail describe the employee record in the
    viewer's company only. Unscoped, a user's record in another company decided
    whether they were listed here and what employee block they showed."""

    @classmethod
    def setUpTestData(cls):
        cls.a = make_company("Rahman Garments")
        cls.b = make_company("Beta Textiles")
        cls.editor = make_user(cls.b, "hr@beta.example")
        # Employee in A (joined) and a plain member of B.
        cls.worker = make_user(cls.a, "worker@example.com")
        CompanyUser.objects.create(user=cls.worker, company=cls.b)
        make_employee(cls.a, "EMP-0001", user=cls.worker, is_joined=True)
        # Joined in A, but a not-yet-joined employee in B.
        cls.pending = make_user(cls.a, "pending@example.com")
        CompanyUser.objects.create(user=cls.pending, company=cls.b)
        make_employee(cls.a, "EMP-0002", user=cls.pending, is_joined=True)
        make_employee(cls.b, "EMP-0001", user=cls.pending, is_joined=False)

    def listed(self, query=""):
        response = self.client_for(self.editor).get("/api/v1/accounts/user-onboards/list" + query)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        return {row["email"]: row for row in body.get("results", body)}

    def test_another_companys_employee_record_is_not_shown_here(self):
        rows = self.listed()
        self.assertIn("worker@example.com", rows)
        self.assertFalse(rows["worker@example.com"]["is_employee"])
        self.assertIsNone(rows["worker@example.com"]["employee"])
        detail = self.client_for(self.editor).get(f"/api/v1/accounts/user-onboards/{self.worker.uid}")
        self.assertIsNone(detail.json()["data"]["employee"])

    def test_joined_elsewhere_does_not_list_someone_still_pending_here(self):
        self.assertNotIn("pending@example.com", self.listed())

    def test_a_user_with_no_company_lists_nobody(self):
        """companyuser__company=None matched every user without a membership, so
        a fresh self-signup could enumerate their names, emails and phones."""
        User.objects.create_user(name="Earlier Signup", email="earlier@example.com", password="pass1234!")
        loner = User.objects.create_user(name="Loner", email="loner@example.com", password="pass1234!")
        response = self.client_for(loner).get("/api/v1/accounts/user-onboards/list?search=earlier")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body.get("results", body), [])

    def test_the_employee_filter_is_scoped_the_same_way(self):
        self.assertNotIn("worker@example.com", self.listed("?is_employee=true"))
        self.assertIn("worker@example.com", self.listed("?is_employee=false"))


class UsEmployeeImportIsOffTests(TestCase):
    def test_every_step_answers_not_implemented(self):
        handler = EmployeesMigrationHandler
        self.assertFalse(handler.import_available)
        self.assertFalse(handler.validate(None, None)["implemented"])
        self.assertFalse(handler.review_impact(None, None)["implemented"])
        self.assertEqual(handler.get_template_headers(), [])
        self.assertIn("not implemented yet", handler.get_metadata()["message"])


class LoginlessEmployeeStrTests(TestCase):
    def test_payroll_rows_print_the_employee_name_without_a_login(self):
        employee = make_employee(make_company("Rahman Garments"), "EMP-0001", name_en="Rina Begum")
        self.assertEqual(str(PayrollSalaryProcess(employee=employee)), "employee_name: Rina Begum")
