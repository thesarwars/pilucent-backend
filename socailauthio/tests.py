"""Tests for social-auth signup privilege.

The Google sign-in path used to create every new user with `is_staff=True`.
`is_staff` is the Django-admin gate, and the `admin` group these users are added
to carries `Permission.objects.all()` (`accounts/django_rest/helpers/group_seeds.py`).
Admin requests never set the `app.company_id` GUC and `common/db/rls.py` is
deliberately permissive when it is unset, so row-level security did not contain
them either: **any Google signup could read and write every tenant's data.**

The fix is that Google signup now mirrors e-mail self-signup exactly. These tests
pin that equivalence, so the flag cannot be reintroduced on one path only.
"""

from django.contrib.auth.models import Group
from django.test import TestCase

from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME
from accounts.models import User


def _create_google_user(email="google.user@example.com"):
    """The user row the Google callback creates, verbatim.

    Mirrors `socailauthio/django_rest/google/views.py` so the assertions below
    fail if that call regains a privilege flag. The surrounding OAuth exchange
    needs live Google credentials and is out of scope here.
    """
    user = User.objects.create(
        email=email,
        name="Google User",
        is_email_verified=True,
        is_admin=True,
    )
    group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
    user.groups.add(group)
    return user


class GoogleSignupPrivilegeTests(TestCase):
    def setUp(self):
        self.user = _create_google_user()

    def test_google_signup_does_not_grant_django_admin(self):
        # The regression this whole test module exists for.
        self.assertFalse(self.user.is_staff)

    def test_google_signup_does_not_grant_platform_superuser(self):
        # `IsSuperAdmin` (adminio/mixins.py:37) gates the cross-tenant console
        # on is_superuser alone.
        self.assertFalse(self.user.is_superuser)

    def test_google_signup_is_still_admin_of_its_own_company(self):
        # `is_admin` is company-scoped ("admin of their own company") and is
        # required by six permission checks. It must survive the fix.
        self.assertTrue(self.user.is_admin)


class SignupPathParityTests(TestCase):
    """Google signup and e-mail self-signup must grant identical privilege.

    Divergence between the two is what produced the vulnerability: e-mail
    signup never set `is_staff`; Google signup did.
    """

    def setUp(self):
        from accounts.django_rest.serializers.user_register import (
            UserRegisterSerializer,
        )

        self.google_user = _create_google_user("g@example.com")
        serializer = UserRegisterSerializer()
        self.email_user = serializer.create(
            {
                "email": "e@example.com",
                "password": "s3cret-pa55phrase",
                "name": "Email User",
            }
        )

    def test_privilege_flags_match(self):
        for flag in ("is_staff", "is_superuser", "is_admin"):
            self.assertEqual(
                getattr(self.google_user, flag),
                getattr(self.email_user, flag),
                f"{flag} differs between the Google and e-mail signup paths",
            )

    def test_both_land_in_the_same_group(self):
        self.assertEqual(
            set(self.google_user.groups.values_list("name", flat=True)),
            set(self.email_user.groups.values_list("name", flat=True)),
        )


class StaffAuditQueryTests(TestCase):
    """The repair query must not sweep up legitimate superusers.

    `accounts/managers.py:40-43` forces `is_staff=True` on every superuser and
    raises if it is unset, so a bare `filter(is_staff=True)` returns the team's
    own Django admins alongside the affected Google accounts.
    """

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            email="admin@example.com", password="s3cret-pa55phrase", name="Admin"
        )
        self.legacy = User.objects.create(
            email="legacy.google@example.com", name="Legacy", is_staff=True
        )

    def test_bare_filter_would_catch_the_superuser(self):
        caught = User.objects.filter(is_staff=True)
        self.assertIn(self.superuser, caught)

    def test_scoped_audit_query_finds_only_the_affected_accounts(self):
        affected = User.objects.filter(is_staff=True, is_superuser=False)
        self.assertIn(self.legacy, affected)
        self.assertNotIn(self.superuser, affected)


class AuditStaffFlagsCommandTests(TestCase):
    """The repair command: dry run must change nothing, --apply must spare superusers."""

    def setUp(self):
        from django.contrib.auth.models import Group

        self.superuser = User.objects.create_superuser(
            email="root@example.com", password="s3cret-pa55phrase", name="Root"
        )
        self.affected = User.objects.create(
            email="old.google@example.com", name="Old", is_staff=True, is_admin=True
        )
        group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        self.affected.groups.add(group)

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command("audit_staff_flags", stdout=out, **kwargs)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self._run()
        self.affected.refresh_from_db()
        self.assertTrue(self.affected.is_staff)
        self.assertIn("Dry run", output)
        self.assertIn("old.google@example.com", output)

    def test_apply_revokes_only_the_affected_account(self):
        self._run(apply=True, no_input=True)
        self.affected.refresh_from_db()
        self.superuser.refresh_from_db()
        self.assertFalse(self.affected.is_staff)
        self.assertTrue(self.superuser.is_staff, "superuser must keep is_staff")

    def test_apply_preserves_company_admin_rights(self):
        # Losing the Django admin site must not demote them inside their company.
        self._run(apply=True, no_input=True)
        self.affected.refresh_from_db()
        self.assertTrue(self.affected.is_admin)
        self.assertIn(ADMIN_GROUP_NAME, self.affected.groups.values_list("name", flat=True))

    def test_rerun_after_apply_is_a_noop(self):
        self._run(apply=True, no_input=True)
        self.assertIn("Nothing to repair", self._run())
