"""Login-access gate for employee-linked accounts.

A user that is linked to an `Employee` may only authenticate when that employee
has `is_access_enabled=True`. SELF_ONBOARD / SELF_ONBOARD_WITH_I9 employees get
access on creation; MANUAL_ENTRY employees stay disabled until an admin sends an
invitation (approve), and access can be revoked later without deleting the
record. Plain (non-employee) users are never blocked by this gate.
"""

ACCESS_DISABLED_MESSAGE = (
    "Your account is not active yet. Please ask your administrator to grant you "
    "access to log in."
)


def has_login_access(user):
    """Return True if `user` is allowed to authenticate.

    With multi-company workspaces a user may be an employee in several
    companies. We allow authentication as long as they can enter *at least one*
    workspace, then enforce access per-company at company selection
    (see ``SelectCompanySerializer``).

    Rules:
      * users with no employee records always pass (plain/admin accounts), and
      * employee-linked users pass when any of their employee records has
        ``is_access_enabled=True``.
    """
    if user is None:
        return False

    employee_access = user.employee_set.values_list("is_access_enabled", flat=True)
    if not employee_access:
        return True

    return any(employee_access)
