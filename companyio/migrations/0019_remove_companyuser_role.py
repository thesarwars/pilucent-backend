from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "0018_copy_role_to_roles"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companyuser",
            name="role",
        ),
    ]
