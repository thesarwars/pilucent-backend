from django.db import migrations


def grant_access_to_existing_employees(apps, schema_editor):
    """Existing employees could already authenticate before this flag existed
    (their account was created with a usable password). Grant access to every
    non-removed employee so the new login gate does not lock anyone out. Only
    employees created after this migration go through the new approve flow.
    """
    Employee = apps.get_model("employeeio", "Employee")
    Employee.objects.exclude(status="REMOVED").update(is_access_enabled=True)


def revoke_all(apps, schema_editor):
    Employee = apps.get_model("employeeio", "Employee")
    Employee.objects.update(is_access_enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0064_employee_is_access_enabled"),
    ]

    operations = [
        migrations.RunPython(
            grant_access_to_existing_employees, reverse_code=revoke_all
        ),
    ]
