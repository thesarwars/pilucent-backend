from django.db import migrations

from accounts.django_rest.helpers.group_seeds import (
    SYSTEM_GROUP_NAMES,
    seed_default_groups,
)


def forward(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    # Initial seed: explicitly populate admin with every existing Permission.
    # Subsequent post_migrate runs leave admin alone so that manual curation
    # via Django admin sticks.
    seed_default_groups(Group, Permission, ContentType, reset_admin=True)


def backward(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=SYSTEM_GROUP_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0040_user_ip_address_and_terms_service"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
