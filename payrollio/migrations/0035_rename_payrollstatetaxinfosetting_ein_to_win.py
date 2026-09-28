from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payrollio", "0034_payrollworklocation_is_primary_and_constraints"),
    ]

    operations = [
        migrations.RenameField(
            model_name="payrollstatetaxinfosetting",
            old_name="ein_number",
            new_name="win_number",
        ),
        migrations.AlterField(
            model_name="payrollstatetaxinfosetting",
            name="win_number",
            field=models.CharField(
                blank=True,
                max_length=15,
                null=True,
                unique=True,
                verbose_name="WIN Number",
            ),
        ),
    ]
