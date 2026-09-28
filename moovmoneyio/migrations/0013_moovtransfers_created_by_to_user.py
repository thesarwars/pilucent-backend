import django.db.models.deletion
from django.db import migrations, models


def employee_created_by_to_user(apps, schema_editor):
    """Remap existing created_by (Employee) values to that employee's User.

    created_by changes from an Employee FK to a User FK. Existing rows hold
    Employee ids, which are invalid as User ids, so remap them via Employee.user
    (lossless) before the new FK constraint is validated. Rows whose employee is
    gone become NULL.
    """
    MoovTransfers = apps.get_model("moovmoneyio", "MoovTransfers")
    Employee = apps.get_model("employeeio", "Employee")

    for transfer in MoovTransfers.objects.exclude(created_by_id=None):
        employee = Employee.objects.filter(pk=transfer.created_by_id).first()
        transfer.created_by_id = employee.user_id if employee else None
        transfer.save(update_fields=["created_by_id"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("moovmoneyio", "0012_moovtransfers_payroll_salary_process"),
    ]

    operations = [
        # 1) Point the model at User but WITHOUT a DB constraint, so the column
        #    can still hold the old Employee ids while we remap them.
        migrations.AlterField(
            model_name="moovtransfers",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="accounts.user",
            ),
        ),
        # 2) Remap Employee id -> that employee's User id.
        migrations.RunPython(employee_created_by_to_user, noop),
        # 3) Add the real FK constraint now that values are valid User ids.
        migrations.AlterField(
            model_name="moovtransfers",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="accounts.user",
            ),
        ),
    ]
