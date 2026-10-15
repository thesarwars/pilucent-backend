"""The four attendance permissions (§11), created now -- Django would
otherwise only create them after migrating -- and added to the `admin`
group, the source of the role builder's available permissions."""

from django.db import migrations

PERMISSIONS = (
    ("write_attendance", "Can adjust attendance and resolve its exceptions"),
    ("acknowledge_attendance", "Can acknowledge a statutory hours breach"),
    ("lock_attendance", "Can lock an attendance period"),
    ("reopen_attendance", "Can reopen a locked attendance period"),
)


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="timekeepingio", model="attendanceaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="timekeepingio",
                              codename__in=[c for c, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("timekeepingio", "0001_attendance"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
    ]
