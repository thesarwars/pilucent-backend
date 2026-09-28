"""Default permission specs for the system Django Groups.

Single source of truth used by:
- accounts/migrations/0041_seed_default_groups.py
- accounts/management/commands/seed_groups.py
- accounts/django_rest/signals/group_seeds.py
"""

ADMIN_GROUP_NAME = "admin"
USER_GROUP_NAME = "user"
EMPLOYEE_GROUP_NAME = "employee"

SYSTEM_GROUP_NAMES = (ADMIN_GROUP_NAME, USER_GROUP_NAME, EMPLOYEE_GROUP_NAME)

# Display labels for the seeded system roles. Code-level identifiers
# (`employee`, `admin`, `user`) stay stable so existing checks and migrations
# keep working; serializers expose `display_name` so the UI can render the
# friendlier product names (e.g. "Employee Self-Service").
SYSTEM_ROLE_DISPLAY_LABELS = {
    ADMIN_GROUP_NAME: "Admin",
    USER_GROUP_NAME: "User",
    EMPLOYEE_GROUP_NAME: "Employee Self-Service",
}

# Spec format: (app_label, model_name_lower, [actions])
# Actions are Django's standard add/change/delete/view.
# "Own-record" filtering (e.g. employee can only see *their own* salary) is
# enforced at the queryset level inside views, not by Django permissions.

# Mirrors the Employee Self-Service role from
# docs/Employee_Self_Service_Role_Permission_Access_Activity.xlsx — only the
# "Own"-access rows of that matrix grant codenames here. "No"-access rows
# (expense reports, employee directory, payroll setup, accounting, sales,
# tax setup, etc.) are intentionally absent.
EMPLOYEE_GROUP_PERMISSIONS = [
    ("attendanceio", "attendance", ["view", "add", "change"]),
    ("attendanceio", "holiday", ["view"]),
    ("leaveio", "leaverequest", ["view", "add", "change"]),
    ("leaveio", "leavetype", ["view"]),
    ("leaveio", "leavebalance", ["view"]),
    ("leaveio", "employeeleaveallocation", ["view"]),
    ("leaveio", "leaveencashment", ["view", "add", "change"]),
    ("employeeio", "employee", ["view", "change"]),
    ("employeeio", "employeesalary", ["view"]),
    ("payrollio", "payrollsalaryprocess", ["view"]),
    ("employeeio", "employeetax", ["view", "change"]),
    ("employeeio", "employeebankinginformation", ["view", "change"]),
    ("fileroomio", "fileitem", ["view", "add"]),
    ("accounts", "user", ["view", "change"]),
]

USER_GROUP_PERMISSIONS = [
    ("companyio", "companyuser", ["view"]),
    ("accounts", "user", ["view", "change"]),
    # Read the chart of accounts, and with it each account's register.
    #
    # `view` only, and deliberately nothing else. This grants sight of the
    # books, not the ability to change them: no `add`/`change`/`delete` on the
    # chart, and none of the `*_bankreconciliation` codenames -- opening and
    # closing a reconciliation writes to the ledger and stays with roles an
    # admin grants on purpose.
    #
    # Until this, an invited co-worker held three permissions, none of them
    # accounting, so every accounting screen was a 403 for the entire
    # population `CompanyRole` exists to serve. Owners never saw it because
    # self-registration sets `is_admin`, which short-circuits the check.
    ("accounts", "chartofaccount", ["view"]),
]


def resolve_permissions(spec, Permission, ContentType):
    """Return Permission objects matching the spec.

    Skips any (app, model) whose ContentType is not yet in the DB. This can
    happen during the initial `migrate` if a downstream app's permissions
    haven't been auto-created when this seed runs; the post_migrate signal
    re-runs the seed afterwards to fill in the gaps.
    """
    ids = []
    for app_label, model, actions in spec:
        try:
            ct = ContentType.objects.get(app_label=app_label, model=model)
        except ContentType.DoesNotExist:
            continue
        codenames = [f"{a}_{model}" for a in actions]
        ids.extend(
            Permission.objects.filter(content_type=ct, codename__in=codenames).values_list(
                "id", flat=True
            )
        )
    return Permission.objects.filter(id__in=ids)


def seed_default_groups(
    Group, Permission, ContentType, *, stdout=None, reset_admin=False
):
    """Idempotently create admin/user/employee groups and apply permissions.

    Admin is the source of truth for the role-builder UI's available
    permission set (see `GroupPermissionsListView`) and is curated by humans
    through Django admin, so this seeder only populates it on first creation
    or when `reset_admin=True` is passed. Manual removals would otherwise be
    silently re-added on every `migrate` (post_migrate re-runs this seeder).

    User / employee are code-driven specs; `.set()` makes spec removals
    propagate so the live Group can never drift past the spec.
    """
    admin, admin_created = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
    user_g, _ = Group.objects.get_or_create(name=USER_GROUP_NAME)
    employee, _ = Group.objects.get_or_create(name=EMPLOYEE_GROUP_NAME)

    if admin_created or reset_admin:
        admin.permissions.set(Permission.objects.all())

    user_g.permissions.set(
        resolve_permissions(USER_GROUP_PERMISSIONS, Permission, ContentType)
    )
    employee.permissions.set(
        resolve_permissions(EMPLOYEE_GROUP_PERMISSIONS, Permission, ContentType)
    )

    if stdout:
        admin_status = (
            "reset" if (admin_created or reset_admin) else "preserved (curated)"
        )
        stdout.write(
            f"Seeded groups -> admin: {admin.permissions.count()} perms ({admin_status}), "
            f"user: {user_g.permissions.count()} perms, "
            f"employee: {employee.permissions.count()} perms"
        )
    return admin, user_g, employee
