"""Login access for an employee's linked account.

Account behaviour carried over from the US module: a user linked to an
employee may authenticate, and enter that company's workspace, only once an
admin grants access; granting it sends the invitation email with a token-based
link, and revoking it is silent. See accounts.django_rest.helpers.login_access.
"""

import os

from django.conf import settings
from django.db import transaction

from accounts.django_rest.helpers.invitation_token import generate_invitation_token
from common.django_rest.helpers.emails import send_email_to_user

INVITATION_TEMPLATE = "emails/onboard/employee_access_granted.html"


class NoLinkedLogin(Exception):
    pass


def set_login_access(employee, enabled):
    """Grant or revoke login access. Returns True when an invitation was sent.

    The flag and the invitation are one step: the row is locked, and a failed
    send rolls the grant back, so a retry sees access still off and sends
    again. Two concurrent grants cannot both send. A revoke needs no login --
    it clears a grant left behind by a login that is gone.
    """
    enabled = bool(enabled)
    with transaction.atomic():
        locked = locked_employee(employee.pk).get()
        # Decided on the locked row, not the caller's copy: the login may have
        # been deleted since that copy was loaded.
        if enabled and locked.user_id is None:
            raise NoLinkedLogin("No login is linked to this employee, so there is no access to grant.")
        granting = enabled and not locked.is_access_enabled
        locked.is_access_enabled = enabled
        locked.save(update_fields=["is_access_enabled", "updated_at"])
        if granting:
            _send_invitation(locked)
    # The caller answers from its own copy (access_out): bring over every field
    # that reads, from the row that was actually locked.
    employee.is_access_enabled = locked.is_access_enabled
    employee.is_joined = locked.is_joined
    employee.user = locked.user
    return granting


def locked_employee(pk):
    """The employee row, locked for update, with its login and company.

    `of=("self",)` is required, not an optimisation: `user` is a nullable FK, so
    select_related makes a LEFT OUTER JOIN, and PostgreSQL refuses a bare
    FOR UPDATE on the nullable side of one. SQLite ignores FOR UPDATE, so the
    test suite cannot catch its absence -- tests_login_access checks it instead.
    """
    from ..models import Employee

    return Employee.objects.select_for_update(of=("self",)).select_related("user", "company").filter(pk=pk)


def _send_invitation(employee):
    user, company = employee.user, employee.company
    frontend_url = getattr(settings, "BASE_FRONTEND_URL", None) or os.environ.get(
        "BASE_FRONTEND_URL", "http://localhost:3000"
    )
    url = f"{frontend_url}/auth/verify-invitation/{generate_invitation_token(user.email)}?emp={employee.uid}"
    send_email_to_user(
        {"company": company, "employee": employee, "url": url},
        INVITATION_TEMPLATE,
        [user.email],
        f"Welcome to {company.name}",
    )
