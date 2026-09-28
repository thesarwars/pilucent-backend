from django.db import migrations


def _backfill_system_company_roles(apps, schema_editor):
    CompanyRole = apps.get_model("adminio", "CompanyRole")

    # System role names are aligned with Django Group names.
    # Use case-insensitive matching to catch older data.
    CompanyRole.objects.filter(name__iexact="admin").update(is_system=True, kind="USER")
    CompanyRole.objects.filter(name__iexact="user").update(is_system=True, kind="USER")
    CompanyRole.objects.filter(name__iexact="employee").update(
        is_system=True, kind="EMPLOYEE"
    )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("adminio", "0005_remove_deprecated_role_models"),
    ]

    operations = [
        migrations.RunPython(_backfill_system_company_roles, _noop_reverse),
    ]
