"""Shared backfill logic for existing companies' CompanyRole data.

Used by both:
- adminio/migrations/0006_backfill_existing_company_roles.py (auto on migrate)
- accounts/management/commands/backfill_company_roles.py     (manual re-run)

Idempotent. Safe to run repeatedly. Never deletes or renames; only adds rows
and retags the legacy `<company.name>_admin` row when it matches exactly.
"""

from accounts.django_rest.helpers.group_seeds import (
    ADMIN_GROUP_NAME,
    EMPLOYEE_GROUP_NAME,
    USER_GROUP_NAME,
)

# Mirror the kind for each of the three system roles. Hard-coded as strings so
# this module works inside a data migration (where the choices class may not be
# importable from a historical model).
SYSTEM_ROLE_SPECS = [
    (ADMIN_GROUP_NAME, "USER"),
    (USER_GROUP_NAME, "USER"),
    (EMPLOYEE_GROUP_NAME, "EMPLOYEE"),
]


def backfill_company_roles(Company, CompanyRole, Group, Permission, *, stdout=None):
    """Ensure every existing Company has the three system CompanyRoles seeded
    and that any legacy `<company.name>_admin` row is tagged is_system=True/USER.

    Pass live or apps.get_model versions of each model.
    """
    seeded = 0
    retagged_system = 0
    retagged_legacy = 0
    permissions_mirrored = 0

    for company in Company.objects.all().iterator():
        for group_name, kind in SYSTEM_ROLE_SPECS:
            role, created = CompanyRole.objects.get_or_create(
                company=company,
                name=group_name,
                defaults={"kind": kind, "is_system": True},
            )
            if created:
                seeded += 1
            elif (not role.is_system) or (role.kind != kind):
                CompanyRole.objects.filter(pk=role.pk).update(
                    is_system=True, kind=kind
                )
                role.is_system = True
                role.kind = kind
                retagged_system += 1

            group = Group.objects.filter(name=group_name).first()
            if group:
                role.permission.set(Permission.objects.filter(group=group))
                permissions_mirrored += 1

        legacy_name = f"{company.name}_admin"
        legacy = CompanyRole.objects.filter(company=company, name=legacy_name).first()
        if legacy and (not legacy.is_system or legacy.kind != "USER"):
            CompanyRole.objects.filter(pk=legacy.pk).update(
                is_system=True, kind="USER"
            )
            retagged_legacy += 1

    if stdout:
        stdout.write(
            f"Backfill complete. Seeded {seeded} new system roles, "
            f"retagged {retagged_system} existing system roles, "
            f"retagged {retagged_legacy} legacy <company>_admin rows, "
            f"mirrored permissions on {permissions_mirrored} role/group pairs."
        )

    return {
        "seeded": seeded,
        "retagged_system": retagged_system,
        "retagged_legacy": retagged_legacy,
        "permissions_mirrored": permissions_mirrored,
    }
