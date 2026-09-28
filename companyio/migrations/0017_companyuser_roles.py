from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "0016_companydesignation_code_and_more"),
        ("adminio", "0004_companyrole_kind_is_system_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyuser",
            name="roles",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Roles assigned to this user in this company. Multiple roles are additive."
                ),
                related_name="company_users",
                to="adminio.companyrole",
            ),
        ),
        migrations.AlterField(
            model_name="companyuser",
            name="permission",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Per-user permission overlay applied on top of the user's roles."
                ),
                to="auth.permission",
            ),
        ),
    ]
