"""User onboarding reached across companies for a user who belongs to two.

Found by the review of the BD employee reconnect, and older than it. The edit
serializer wrote roles and permissions onto `companyuser_set.first()` -- the
user's first membership in ANY company -- with roles taken from the editor's
company, and the list and detail showed that same arbitrary membership. An
admin of one company could rewrite a user's roles in another.

Still open, deliberately: DELETE soft-deletes the user and their employee
records in every company. Removing only this company's membership is not a
safe fix -- US payroll and tax queries reach a company's runs through the
membership row (`employee__user__companyuser__company`), so a deleted row
drops that company's payroll history and filings. It needs a membership
status flag, or those queries scoped by `employee__company` first
(docs/employee-reconnect-backlog.md).
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from adminio.models import CompanyRole
from companyio.models import Company, CompanyUser
from employeeio.models import Employee

BASE = "/api/v1/accounts/user-onboards"


def member(company, email, name="Member"):
    user = User.objects.create_user(name=name, email=email, password="pass1234!")
    CompanyUser.objects.create(user=user, company=company)
    return user


@override_settings(SECURE_SSL_REDIRECT=False)
class OnboardingAcrossCompaniesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Company.objects.create(name="Acme Garments")
        cls.b = Company.objects.create(name="Beta Textiles")
        cls.viewer_a = CompanyRole.objects.create(company=cls.a, name="viewer")
        cls.manager_b = CompanyRole.objects.create(company=cls.b, name="manager")
        # The shared user: a member of A (with A's role) and of B.
        cls.shared = member(cls.a, "shared@example.com", "Shared")
        CompanyUser.objects.get(user=cls.shared, company=cls.a).roles.add(cls.viewer_a)
        CompanyUser.objects.create(user=cls.shared, company=cls.b)
        Employee.objects.create(company=cls.a, user=cls.shared, code="EMP-0001", name_en="Shared", is_joined=True)
        Employee.objects.create(company=cls.b, user=cls.shared, code="EMP-0001", name_en="Shared", is_joined=True)
        # The editor works in B only, so B is their active company.
        cls.editor = member(cls.b, "hr@beta.example", "HR")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.editor)

    def membership(self, company):
        return CompanyUser.objects.get(user=self.shared, company=company)

    def test_editing_roles_writes_only_the_editors_company(self):
        response = self.api.patch(
            f"{BASE}/{self.shared.uid}", {"role_uids": [str(self.manager_b.uid)]}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(self.membership(self.b).roles.all()), [self.manager_b])
        self.assertEqual(list(self.membership(self.a).roles.all()), [self.viewer_a])

    def test_the_membership_shown_is_the_one_in_the_viewers_company(self):
        detail = self.api.get(f"{BASE}/{self.shared.uid}").json()["data"]
        self.assertEqual(detail["company_user"]["company"], "Beta Textiles")
        self.assertEqual(detail["company_user"]["roles"], [])
        rows = {row["email"]: row for row in self.api.get(f"{BASE}/list").json()["results"]}
        self.assertEqual(rows["shared@example.com"]["company_user"]["company"], "Beta Textiles")

    def test_the_patch_response_shows_the_roles_just_written(self):
        response = self.api.patch(
            f"{BASE}/{self.shared.uid}", {"role_uids": [str(self.manager_b.uid)]}, format="json"
        )
        roles = [r["name"] for r in response.json()["data"]["company_user"]["roles"]]
        self.assertEqual(roles, ["manager"])

    def test_the_list_has_a_stable_default_order(self):
        member(self.b, "later@example.com", "Later")
        emails = [row["email"] for row in self.api.get(f"{BASE}/list").json()["results"]]
        self.assertEqual(emails[0], "later@example.com")
