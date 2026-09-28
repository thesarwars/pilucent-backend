"""Create section-level Permission rows for the Reports area.

These permissions are not tied to any real database table. We create a
ContentType with app_label='adminio' and model='reportpermission' to anchor
four Permission rows that represent section-level access to the entire
reports feature.
"""

from django.db import migrations


def create_report_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    ct, _ = ContentType.objects.get_or_create(
        app_label="adminio",
        model="reportpermission",
    )

    permissions = [
        ("view_reports", "Can view reports"),
        ("add_reports", "Can add/create reports"),
        ("change_reports", "Can edit reports"),
        ("delete_reports", "Can delete reports"),
    ]

    for codename, name in permissions:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={"name": name},
        )


def remove_report_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    try:
        ct = ContentType.objects.get(app_label="adminio", model="reportpermission")
    except ContentType.DoesNotExist:
        return

    Permission.objects.filter(
        content_type=ct,
        codename__in=[
            "view_reports",
            "add_reports",
            "change_reports",
            "delete_reports",
        ],
    ).delete()
    ct.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("adminio", "0008_resync_employee_role_permissions"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(
            create_report_permissions,
            reverse_code=remove_report_permissions,
        ),
    ]
