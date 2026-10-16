"""Salary structures move onto the pay library (1 of 3): the new columns.
Split in three so Postgres never alters a table in the transaction that
just wrote to it."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0007_attendance"),
        ("paylibio", "0001_paylib"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeesalarystructure",
            name="library_template",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="+", to="paylibio.structuretemplate"),
        ),
        migrations.AddField(
            model_name="employeesalarycomponent",
            name="component_version",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
