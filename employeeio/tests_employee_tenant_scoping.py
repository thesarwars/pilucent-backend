"""Every employee sub-resource is scoped by company, not by the key in the URL.

Carried over from the US module, where sixteen views filtered sub-records on
`employee__uid` from the URL with no company anywhere -- read, write and
delete across tenants, over banking information, tax records and wage
garnishments.

The BD tables have no RLS, and the sub-records carry no `company` of their
own, so an object-level permission comparing `obj.company` could never help:
the company filter written in the view is the only protection. The BD API keys
on the business code (`EMP-0142`), which is unique per company, not globally
-- two tenants can both have an EMP-0142 -- so an unscoped code lookup is not
merely a leak but a guaranteed collision.
"""

import inspect
from decimal import Decimal

from django.test import TestCase

from employeeio.models import (
    EmployeeFieldHistory,
    EmployeeInvestment,
    EmployeeNominee,
    EmployeePaymentProfile,
    EmployeeStatutory,
    EmployeeTaxProfile,
)
from employeeio.test_support import ApiMixin, give_structure, make_company, make_employee, make_user, seed_rules, url


class SubRecordShapeTests(TestCase):
    def test_the_sub_records_have_no_company_field(self):
        """Why the view's company filter is the only thing scoping them."""
        for model in (EmployeeNominee, EmployeeStatutory, EmployeeTaxProfile, EmployeeInvestment,
                      EmployeePaymentProfile, EmployeeFieldHistory):
            fields = {f.name for f in model._meta.get_fields()}
            with self.subTest(model=model.__name__):
                self.assertNotIn("company", fields)
                self.assertIn("employee", fields)


class CrossTenantTests(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company_a = make_company("Acme Garments")
        cls.company_b = make_company("Beta Textiles")
        cls.user_a = make_user(cls.company_a, "a@example.com")
        cls.user_b = make_user(cls.company_b, "b@example.com")
        cls.emp_a = make_employee(cls.company_a, "EMP-0142", name_en="Ada Rahman", father_name="A Senior")
        EmployeeNominee.objects.create(employee=cls.emp_a, name="A Nominee", share=Decimal("100"))
        give_structure(cls.emp_a, 30000)

    def setUp(self):
        super().setUp()
        self.as_a = self.client_for(self.user_a)
        self.as_b = self.client_for(self.user_b)

    def test_b_cannot_read_any_part_of_as_employee(self):
        for suffix in ("", "/compliance", "/tax-projection", "/nominees", "/investments", "/history", "/salary"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.as_b.get(url("EMP-0142", suffix)).status_code, 404)
                self.assertEqual(self.as_a.get(url("EMP-0142", suffix)).status_code, 200)

    def test_b_cannot_write_to_as_employee(self):
        for suffix, body in (("/personal", {"fatherName": "Injected"}), ("/payment", {"bank": "Injected"}),
                             ("/statutory", {"insurer": "Injected"}), ("/tax-profile", {"etin": "999"}),
                             ("/employment", {"grade": "G1"})):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.as_b.patch(url("EMP-0142", suffix), body, format="json").status_code, 404)
        replace = {"nominees": [{"name": "Injected", "share": "100"}]}
        self.assertEqual(self.as_b.put(url("EMP-0142", "/nominees"), replace, format="json").status_code, 404)
        self.emp_a.refresh_from_db()
        self.assertEqual(self.emp_a.father_name, "A Senior")
        self.assertEqual(list(self.emp_a.nominees.values_list("name", flat=True)), ["A Nominee"])

    def test_the_same_code_in_two_companies_resolves_to_each_callers_own(self):
        make_employee(self.company_b, "EMP-0142", name_en="Bo Karim")
        self.assertEqual(self.as_a.get(url("EMP-0142")).json()["personal"]["nameEn"], "Ada Rahman")
        self.assertEqual(self.as_b.get(url("EMP-0142")).json()["personal"]["nameEn"], "Bo Karim")
        self.assertEqual(self.as_b.get(url("EMP-0142", "/nominees")).json()["nominees"], [])

    def test_the_roster_lists_only_the_callers_company(self):
        make_employee(self.company_b, "EMP-0001", name_en="Bo Karim")
        self.assertEqual([r["code"] for r in self.as_b.get(url()).json()["results"]], ["EMP-0001"])

    def test_an_admin_of_b_cannot_touch_as_login_access(self):
        """The access endpoint is admin-only, but admin *of B* is still not A."""
        from employeeio.tests_login_access import make_company_admin

        make_company_admin(self.user_b, self.company_b)
        login = make_user(self.company_a, "a-worker@example.com")
        self.emp_a.user = login
        self.emp_a.is_access_enabled = True
        self.emp_a.save()
        response = self.as_b.patch(url("EMP-0142", "/access"), {"isAccessEnabled": False}, format="json")
        self.assertEqual(response.status_code, 404)
        self.emp_a.refresh_from_db()
        self.assertTrue(self.emp_a.is_access_enabled)


class CallSiteTests(TestCase):
    """Guards against a new sub-resource being added without scoping."""

    def source(self):
        from weapi.django_rest.views import bd_employees

        return inspect.getsource(bd_employees)

    def test_every_employee_code_filter_is_paired_with_a_company_filter(self):
        lines = self.source().split("\n")
        found = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith(("employee__code=", "employee__uid=")):
                continue
            found += 1
            window = "\n".join(lines[i : i + 2])
            with self.subTest(line=i + 1):
                self.assertIn("employee__company=", window, f"line {i + 1} filters by employee with no company scope")
        self.assertGreaterEqual(found, 6)

    def test_the_employee_itself_is_resolved_with_its_company(self):
        source = self.source()
        self.assertIn('code=self.kwargs["code"],\n            company=self.company(),', source)
        bare = [line for line in source.split("\n") if line.strip() == 'code=self.kwargs["code"],']
        self.assertEqual(len(bare), 1, "the employee is resolved in one place, get_employee()")
