"""Login access is account behaviour, and it survives the BD employee rebuild.

The strip removed the US `Employee.is_access_enabled` along with the rest of
the US model. `has_login_access` builds its query on that column, so every
login -- password, TOTP, Google, onboarding -- raised FieldError, including
for users with no employee record at all. And the only way to grant access
lived in the removed US employee API. The field is restored with its old
default, and granting it is an endpoint on the BD API, open only to an admin
of the active company -- not to anyone carrying the global `is_admin` flag,
which every self-signup has -- that sends the invitation email.
"""

from unittest import mock

from django.core import mail
from django.test import TestCase

from accounts.django_rest.helpers.login_access import has_login_access
from accounts.models import User
from adminio.models import CompanyRole
from companyio.models import CompanyUser
from employeeio.models import Employee
from employeeio.services import access
from employeeio.test_support import ApiMixin, make_company, make_employee, make_user, seed_rules, url


class LoginGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Rahman Garments")

    def test_a_user_with_no_employee_record_passes(self):
        """The regression: this raised FieldError for everybody."""
        self.assertTrue(has_login_access(make_user(self.company, "plain@example.com")))

    def test_a_linked_employee_needs_access_granted(self):
        user = make_user(self.company, "worker@example.com")
        employee = make_employee(self.company, "EMP-0001", user=user)
        self.assertFalse(has_login_access(user))
        employee.is_access_enabled = True
        employee.save()
        self.assertTrue(has_login_access(user))

    def test_a_new_superuser_gets_an_employee_in_their_home_company(self):
        superuser = User.objects.create_superuser(name="Ops", email="ops@example.com", password="pass1234!")
        employee = Employee.objects.get(user=superuser)
        self.assertEqual(employee.company.name, "Ops-organization")
        self.assertEqual((employee.code, employee.name_en, employee.email), ("EMP-0001", "Ops", "ops@example.com"))
        self.assertFalse(employee.is_access_enabled)


def make_company_admin(user, company):
    """Give `user` the company's seeded system admin role."""
    role, _ = CompanyRole.objects.get_or_create(company=company, name="admin", defaults={"is_system": True})
    if not role.is_system:
        role.is_system = True
        role.save()
    CompanyUser.objects.get(user=user, company=company).roles.add(role)


class AccessEndpointTests(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        # An admin of this company by role, without the global flag.
        cls.admin = make_user(cls.company, "admin@example.com")
        make_company_admin(cls.admin, cls.company)
        cls.member = make_user(cls.company, "member@example.com")
        # A plain member of this company who carries the global flag, as every
        # self-signup does from the company it created.
        cls.flagged = make_user(cls.company, "flagged@example.com")
        cls.flagged.is_admin = True
        cls.flagged.save()
        cls.login = make_user(cls.company, "worker@example.com")

    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142", user=self.login)

    def patch(self, user, body, code="EMP-0142"):
        return self.client_for(user).patch(url(code, "/access"), body, format="json")

    def test_granting_access_sends_the_invitation_and_revoking_is_silent(self):
        response = self.patch(self.admin, {"isAccessEnabled": True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"isAccessEnabled": True, "isJoined": False,
                                           "login": "worker@example.com", "invitationSent": True})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["worker@example.com"])
        sent = mail.outbox[0].body + str(mail.outbox[0].alternatives)
        self.assertIn(f"?emp={self.employee.uid}", sent)
        # The US template printed the email as the password; that was only true
        # of the US signup flow.
        self.assertNotIn("Password", sent)
        self.assertTrue(has_login_access(self.login))

        again = self.patch(self.admin, {"isAccessEnabled": True})
        self.assertFalse(again.json()["invitationSent"])
        self.patch(self.admin, {"isAccessEnabled": False})
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(has_login_access(self.login))

    def test_only_an_admin_of_this_company_may_grant(self):
        self.assertEqual(self.patch(self.member, {"isAccessEnabled": True}).status_code, 403)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_access_enabled)

    def test_the_global_admin_flag_is_not_admin_of_this_company(self):
        """The regression: IsCompanyAdmin let this user revoke the owner's login."""
        self.employee.is_access_enabled = True
        self.employee.save()
        self.assertEqual(self.patch(self.flagged, {"isAccessEnabled": False}).status_code, 403)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_access_enabled)

    def test_a_failed_invitation_leaves_access_off(self):
        """The grant and the email are one step, so a retry sends again."""
        with mock.patch.object(access, "send_email_to_user", side_effect=OSError("smtp down")):
            with self.assertRaises(OSError):
                access.set_login_access(self.employee, True)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_access_enabled)
        self.assertTrue(access.set_login_access(self.employee, True))
        self.assertEqual(len(mail.outbox), 1)

    def test_the_lock_is_on_the_employee_row_only(self):
        """PostgreSQL refuses a bare FOR UPDATE across the LEFT OUTER JOIN to the
        nullable login -- every grant and revoke was a 500 in production. SQLite
        ignores FOR UPDATE, so the query itself is what is checked."""
        self.assertEqual(access.locked_employee(self.employee.pk).query.select_for_update_of, ("self",))

    def test_a_login_deleted_after_loading_is_a_conflict_not_a_crash(self):
        stale = Employee.objects.get(pk=self.employee.pk)
        self.login.delete()
        with self.assertRaises(access.NoLinkedLogin):
            access.set_login_access(stale, True)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_revoke_racing_a_login_delete_answers_from_the_locked_row(self):
        from weapi.django_rest.serializers.bd_employees import access_out

        self.employee.is_access_enabled = True
        self.employee.is_joined = True
        self.employee.save()
        stale = Employee.objects.get(pk=self.employee.pk)
        self.login.delete()
        access.set_login_access(stale, False)
        self.assertEqual(access_out(stale), {"isAccessEnabled": False, "isJoined": False, "login": None})

    def test_the_invitation_omits_contact_lines_the_company_lacks(self):
        self.company.email = None
        self.company.phone = None
        self.company.save()
        self.patch(self.admin, {"isAccessEnabled": True})
        sent = mail.outbox[0].body + str(mail.outbox[0].alternatives)
        self.assertNotIn("None", sent)

    def test_granting_without_a_linked_login_is_a_conflict(self):
        make_employee(self.company, "EMP-0200")
        response = self.patch(self.admin, {"isAccessEnabled": True}, code="EMP-0200")
        self.assertEqual(response.status_code, 409)
        self.assertIn("No login is linked", response.json()["message"])

    def test_revoking_needs_no_linked_login(self):
        orphan = make_employee(self.company, "EMP-0201", is_access_enabled=True)
        response = self.patch(self.admin, {"isAccessEnabled": False}, code="EMP-0201")
        self.assertEqual(response.status_code, 200, response.content)
        orphan.refresh_from_db()
        self.assertFalse(orphan.is_access_enabled)

    def test_deleting_the_login_clears_its_grant(self):
        """Employee.user is SET_NULL; the grant belonged to the login and must not
        pass to whoever is linked next."""
        self.employee.is_access_enabled = True
        self.employee.is_joined = True
        self.employee.save()
        self.login.delete()
        self.employee.refresh_from_db()
        self.assertIsNone(self.employee.user_id)
        self.assertFalse(self.employee.is_access_enabled)
        self.assertFalse(self.employee.is_joined)

    def test_the_value_must_be_a_boolean_in_an_object(self):
        self.assertEqual(self.patch(self.admin, {"isAccessEnabled": "yes"}).status_code, 400)
        self.assertEqual(self.patch(self.admin, [True]).status_code, 400)

    def test_the_profile_shows_access(self):
        body = self.client_for(self.member).get(url("EMP-0142")).json()
        self.assertEqual(body["access"], {"isAccessEnabled": False, "isJoined": False, "login": "worker@example.com"})
