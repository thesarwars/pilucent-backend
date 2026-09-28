# Generated manually for primary tax onboarding

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payrollio", "0033_payrollsalaryprocess_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollworklocation",
            name="is_primary",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddConstraint(
            model_name="payrollgeneraltaxsetting",
            constraint=models.UniqueConstraint(
                fields=("company",),
                name="unique_payroll_general_tax_setting_per_company",
            ),
        ),
        migrations.AddConstraint(
            model_name="payrollworklocation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_primary", True)),
                fields=("company",),
                name="unique_primary_payroll_work_location_per_company",
            ),
        ),
    ]
