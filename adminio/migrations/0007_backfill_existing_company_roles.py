from django.db import migrations

from adminio.django_rest.helpers.role_backfill import backfill_company_roles


def forward(apps, schema_editor):
    Company = apps.get_model("companyio", "Company")
    CompanyRole = apps.get_model("adminio", "CompanyRole")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    backfill_company_roles(Company, CompanyRole, Group, Permission)


def backward(apps, schema_editor):
    """No-op reverse: backfill only adds + retags rows. Nothing safe to remove."""
    pass


class Migration(migrations.Migration):
    """Per-company backfill: seed system roles + retag legacy `<company>_admin`.

    Runs after 0006_backfill_system_company_roles, which handles the simple
    case-insensitive retag of rows already named admin/user/employee. This
    migration goes further: it ensures every Company has all three system
    rows (creating any missing ones) and mirrors the matching Django Group's
    permissions onto each role.

    Note on Permission availability: when this runs as part of a fresh
    `migrate`, auth.Permission rows for apps that migrate AFTER adminio may
    not exist yet. That's acceptable - the post_migrate signal in
    accounts/apps.py re-seeds the Django Groups at the end of migrate, and
    `python manage.py backfill_company_roles` can be re-run any time to
    mirror the freshly-added permissions onto the per-company CompanyRoles.
    """

    dependencies = [
        ("adminio", "0006_backfill_system_company_roles"),
        ("accounts", "0041_seed_default_groups"),
        ("companyio", "0019_remove_companyuser_role"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
