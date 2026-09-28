# Hand-written: adds the `status` lifecycle column to PayrollSalaryProcess.
# Existing rows are backfilled from `is_salary_done` so prior finalized
# history immediately counts toward YTD and wage-cap totals.

from django.db import migrations, models


def backfill_status_from_is_salary_done(apps, schema_editor):
    PayrollSalaryProcess = apps.get_model("payrollio", "PayrollSalaryProcess")
    PayrollSalaryProcess.objects.filter(is_salary_done=True).update(status="FINALIZED")
    PayrollSalaryProcess.objects.filter(is_salary_done=False).update(status="DRAFT")


def reverse_backfill_noop(apps, schema_editor):
    # Reversing the schema change drops the column; the data goes with it,
    # so there's nothing to undo at the data layer.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("payrollio", "0032_alter_taxcenterpaymethod_liability_period"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsalaryprocess",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("FINALIZED", "Finalized"),
                    ("VOIDED", "Voided"),
                ],
                db_index=True,
                default="DRAFT",
                help_text=(
                    "Lifecycle of the run. Only FINALIZED rows count toward "
                    "YTD and wage-cap enforcement. Voided rows are excluded "
                    "so reversals automatically subtract from cumulative "
                    "totals."
                ),
                max_length=16,
            ),
        ),
        migrations.RunPython(
            backfill_status_from_is_salary_done,
            reverse_backfill_noop,
        ),
    ]
