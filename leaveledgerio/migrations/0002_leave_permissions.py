"""The six leave permissions (§8), created now -- Django would otherwise only
create them after migrating -- and added to the `admin` group, the source of
the role builder's available permissions."""

from django.db import migrations

PERMISSIONS = (
    ("apply_leave", "Can submit leave and encashment on an employee's behalf"),
    ("approve_leave", "Can approve or decline leave"),
    ("grant_leave", "Can grant, debit or correct leave"),
    ("approve_encashment", "Can approve and pay a leave encashment"),
    ("close_leave_year", "Can post accruals and close the leave year"),
    ("read_maternity_restricted", "Can read restricted maternity fields"),
)


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="leaveledgerio", model="leaveaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="leaveledgerio",
                              codename__in=[c for c, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leaveledgerio", "0001_leave"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
    ]
