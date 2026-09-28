# Generated for linking purchase to expense report and tracking payment date

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0057_employeeexpensereport_status_previous"),
        ("purchaseio", "0023_alter_paybill_email_alter_purchase_email_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeexpensereport",
            name="purchase",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="employee_expense_reports",
                to="purchaseio.purchase",
            ),
        ),
        migrations.AddField(
            model_name="employeeexpensereport",
            name="payment_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
