"""Tests for the multi-company workspace switcher: login memberships, scoped
JWT select/switch, pin, invite-existing-user + join-by-code, and tenant context.
"""

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from accounts.django_rest.helpers.workspace import (
    COMPANY_ID_CLAIM,
    COMPANY_UID_CLAIM,
)
from adminio.models import CompanyRole
from common.middleware.tenant import TenantContextMiddleware
from common.tenant import (
    get_current_company_id,
    tenant_unscoped,
    use_company_id,
)
from companyio.choices import CompanyInvitationStatusChoices
from companyio.django_rest.helpers.invitations import create_invitation
from companyio.models import Company, CompanyUser


def make_user(email, name="Test User", password="pass1234!"):
    return User.objects.create_user(name=name, email=email, password=password)


def make_company(name, ein=None):
    return Company.objects.create(name=name, business_id_no=ein)


def add_membership(user, company, *, owner=False):
    cu = CompanyUser.objects.create(user=user, company=company)
    if owner:
        role = CompanyRole.objects.create(
            company=company, name="admin", is_system=True
        )
        cu.roles.add(role)
    return cu


# SECURE_SSL_REDIRECT is on in settings, which would 301 every plain test
# request; disable it for these API tests.
no_ssl_redirect = override_settings(SECURE_SSL_REDIRECT=False)


class WorkspaceSetupMixin:
    def setUp(self):
        super().setUp()
        self.user = make_user("amara@example.com", name="Amara Osei")
        self.company_a = make_company("Acme Books", ein="12-3456789")
        self.company_b = make_company("Beta Ledger", ein="98-7654321")
        add_membership(self.user, self.company_a, owner=True)
        add_membership(self.user, self.company_b, owner=False)


@no_ssl_redirect
class LoginMembershipsTests(WorkspaceSetupMixin, APITestCase):
    def test_login_returns_memberships_and_summary(self):
        resp = self.client.post(
            reverse("token_obtain_pair"),
            {"email": "amara@example.com", "password": "pass1234!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIn("access", data)
        self.assertEqual(len(data["memberships"]), 2)
        self.assertEqual(data["summary"], {"total": 2, "owned": 1, "managed": 1})
        # Login token is unscoped (no company claim yet).
        access = AccessToken(data["access"])
        self.assertIsNone(access.get(COMPANY_ID_CLAIM))


@no_ssl_redirect
class SelectCompanyTests(WorkspaceSetupMixin, APITestCase):
    def test_select_company_mints_scoped_token_and_stamps_last_opened(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            reverse("workspace_select_company"),
            {"company_uid": str(self.company_a.uid)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        access = AccessToken(resp.json()["access"])
        self.assertEqual(access[COMPANY_ID_CLAIM], self.company_a.id)
        self.assertEqual(access[COMPANY_UID_CLAIM], str(self.company_a.uid))

        cu = CompanyUser.objects.get(user=self.user, company=self.company_a)
        self.assertIsNotNone(cu.last_opened_at)

    def test_select_company_denied_for_non_member(self):
        other = make_company("Gamma Inc")
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            reverse("workspace_select_company"),
            {"company_uid": str(other.uid)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


@no_ssl_redirect
class PinCompanyTests(WorkspaceSetupMixin, APITestCase):
    def test_pin_toggles(self):
        self.client.force_authenticate(self.user)
        url = reverse("workspace_pin_company")
        resp = self.client.post(
            url, {"company_uid": str(self.company_b.uid)}, format="json"
        )
        self.assertTrue(resp.json()["company"]["is_pinned"])
        resp = self.client.post(
            url, {"company_uid": str(self.company_b.uid)}, format="json"
        )
        self.assertFalse(resp.json()["company"]["is_pinned"])


@no_ssl_redirect
class InviteExistingUserTests(WorkspaceSetupMixin, APITestCase):
    def test_existing_user_joins_second_company_by_code(self):
        # 'invitee' already has an account and belongs to company_b only.
        invitee = make_user("dev@example.com", name="Dev")
        add_membership(invitee, self.company_b)

        invitation = create_invitation(
            company=self.company_a,
            email="dev@example.com",
            roles=[],
            invited_by=self.user,
        )
        # No membership in company_a yet (deferred until acceptance).
        self.assertFalse(
            CompanyUser.objects.filter(
                user=invitee, company=self.company_a
            ).exists()
        )

        self.client.force_authenticate(invitee)
        resp = self.client.post(
            reverse("workspace_join_by_code"),
            {"code": invitation.code},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # Membership now exists and the invitation is accepted.
        self.assertTrue(
            CompanyUser.objects.filter(
                user=invitee, company=self.company_a
            ).exists()
        )
        invitation.refresh_from_db()
        self.assertEqual(
            invitation.status, CompanyInvitationStatusChoices.ACCEPTED
        )
        # Response carries a company-scoped token for the joined company.
        access = AccessToken(resp.json()["access"])
        self.assertEqual(access[COMPANY_ID_CLAIM], self.company_a.id)

    def test_join_by_code_rejects_email_mismatch(self):
        invitation = create_invitation(
            company=self.company_a,
            email="someone-else@example.com",
            roles=[],
            invited_by=self.user,
        )
        outsider = make_user("outsider@example.com")
        self.client.force_authenticate(outsider)
        resp = self.client.post(
            reverse("workspace_join_by_code"),
            {"code": invitation.code},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class BillingCompanyResolverTests(WorkspaceSetupMixin, TestCase):
    def _request(self, data):
        from types import SimpleNamespace

        return SimpleNamespace(user=self.user, data=data)

    def test_explicit_company_uid_targets_that_company(self):
        from weapi.django_rest.helpers.billing import resolve_billing_company

        company = resolve_billing_company(
            self._request({"company_uid": str(self.company_b.uid)})
        )
        self.assertEqual(company, self.company_b)

    def test_unknown_company_uid_is_rejected(self):
        from rest_framework.serializers import ValidationError
        from weapi.django_rest.helpers.billing import resolve_billing_company

        other = make_company("Outsider Co")
        with self.assertRaises(ValidationError):
            resolve_billing_company(
                self._request({"company_uid": str(other.uid)})
            )

    def test_falls_back_to_active_company(self):
        from weapi.django_rest.helpers.billing import resolve_billing_company

        with use_company_id(self.company_b.id):
            company = resolve_billing_company(self._request({}))
        self.assertEqual(company, self.company_b)


class TenantContextTests(WorkspaceSetupMixin, TestCase):
    def test_get_active_company_follows_context(self):
        # With company_b in context, get_active_company resolves to B...
        with use_company_id(self.company_b.id):
            self.assertEqual(self.user.get_active_company(), self.company_b)
        # ...and a company the user does not belong to yields None (no widening).
        stranger_company = make_company("Stranger Co")
        with use_company_id(stranger_company.id):
            self.assertIsNone(self.user.get_active_company())
        # No context -> legacy fallback to a membership.
        self.assertIsNotNone(self.user.get_active_company())

    def test_tenant_unscoped_clears_and_restores_context(self):
        # Cross-company operations (e.g. creating a new company) must run with
        # no active company so RLS is permissive; the prior context is restored.
        with use_company_id(self.company_a.id):
            self.assertEqual(get_current_company_id(), self.company_a.id)
            with tenant_unscoped():
                self.assertIsNone(get_current_company_id())
            self.assertEqual(get_current_company_id(), self.company_a.id)

    def test_middleware_sets_context_from_scoped_token(self):
        token = AccessToken()
        token[COMPANY_ID_CLAIM] = self.company_a.id

        captured = {}

        def get_response(request):
            captured["company_id"] = get_current_company_id()
            return "ok"

        mw = TenantContextMiddleware(get_response)
        request = RequestFactory().get(
            "/", HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        mw(request)
        self.assertEqual(captured["company_id"], self.company_a.id)
        # Context is cleared after the request.
        self.assertIsNone(get_current_company_id())
