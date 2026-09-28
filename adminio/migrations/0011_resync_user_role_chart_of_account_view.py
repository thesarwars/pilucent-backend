"""Re-sync the system `user` role to the updated spec.

`USER_GROUP_PERMISSIONS` gained `view_chartofaccount`, which is what the Bank
Register and the chart of accounts now require. `post_migrate` re-runs the
seeder, but only at the very end of the `migrate` command -- so on an existing
database the Group still holds the previous set while any RunPython in this
deploy runs, and the mirrored CompanyRole rows would keep the old set until
something else resynced them.

Same shape and same reason as `0008_resync_employee_role_permissions`.
"""

from django.db import migrations

from accounts.django_rest.helpers.group_seeds import seed_default_groups
from adminio.django_rest.helpers.role_backfill import backfill_company_roles


def forward(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Company = apps.get_model("companyio", "Company")
    CompanyRole = apps.get_model("adminio", "CompanyRole")

    seed_default_groups(Group, Permission, ContentType)
    backfill_company_roles(Company, CompanyRole, Group, Permission)


def backward(apps, schema_editor):
    """No-op: forward is a permission resync, nothing safe to undo."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("adminio", "0010_alter_companyrole_options"),
        ("accounts", "0041_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
