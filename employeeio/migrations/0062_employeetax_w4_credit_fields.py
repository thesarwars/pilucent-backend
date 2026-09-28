# Generated manually for EmployeeTax W-4 credit fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0061_backfill_employee_profile_from_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeetax",
            name="exempt_fields",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
        migrations.AddField(
            model_name="employeetax",
            name="children_under_17",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeetax",
            name="other_dependents",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeetax",
            name="other_tax_credits",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employeetax",
            name="children_amount",
            field=models.DecimalField(
                decimal_places=3, default=0.0, max_digits=19
            ),
        ),
        migrations.AddField(
            model_name="employeetax",
            name="dependent_amount",
            field=models.DecimalField(
                decimal_places=3, default=0.0, max_digits=19
            ),
        ),
        migrations.AddField(
            model_name="employeetax",
            name="total_credits",
            field=models.DecimalField(
                decimal_places=3, default=0.0, max_digits=19
            ),
        ),
    ]
