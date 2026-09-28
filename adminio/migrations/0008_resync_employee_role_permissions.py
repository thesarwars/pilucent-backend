from django.db import migrations

from accounts.django_rest.helpers.group_seeds import seed_default_groups
from adminio.django_rest.helpers.role_backfill import backfill_company_roles


def forward(apps, schema_editor):
    """Re-sync the system `employee` CompanyRole permissions to the updated
    Employee Self-Service spec.

    The Group must be re-seeded inside this migration before mirroring,
    because post_migrate fires only at the end of the `migrate` command — so
    on an existing DB the Group still holds the previous permission set when
    this RunPython runs.
    """
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
        ("adminio", "0007_backfill_existing_company_roles"),
        ("accounts", "0041_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
