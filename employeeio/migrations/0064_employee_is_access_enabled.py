from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0063_remove_employee_legacy_address_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="is_access_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
