# Migration: Replace NEEDS_INFO with REQUEST_CHANGES, add REVIEW/REQUEST_CHANGES/PAID

from django.db import migrations, models


def needs_info_to_request_changes(apps, schema_editor):
    EmployeeExpenseReport = apps.get_model("employeeio", "EmployeeExpenseReport")
    EmployeeExpenseReport.objects.filter(status="NEEDS_INFO").update(status="REQUEST_CHANGES")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0053_employeeexpensereport_approved_by"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeeexpensereport",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("SUBMITTED", "Submitted"),
                    ("REVIEW", "Review"),
                    ("REQUEST_CHANGES", "Request Changes"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                    ("PAID", "Paid"),
                ],
                default="DRAFT",
                max_length=50,
            ),
        ),
        migrations.RunPython(needs_info_to_request_changes, noop),
    ]
