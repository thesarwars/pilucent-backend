"""Backfill Employee.company from each employee's user membership.

Before multi-tenancy, an Employee derived its company indirectly via
``user.get_active_company()`` (the user's first CompanyUser). Every existing
user belongs to at most one company, so that single membership is the
unambiguous company for each legacy Employee row. We copy it onto the new
``company`` FK so the relationship is explicit going forward.
"""

from django.db import migrations


def backfill_company(apps, schema_editor):
    Employee = apps.get_model("employeeio", "Employee")
    CompanyUser = apps.get_model("companyio", "CompanyUser")

    # Map user_id -> company_id from existing memberships. With one membership
    # per user today this is unambiguous; if a user somehow has several, the
    # earliest membership wins (matches the old "first()" behaviour).
    user_to_company = {}
    for cu in CompanyUser.objects.order_by("created_at").values(
        "user_id", "company_id"
    ):
        user_to_company.setdefault(cu["user_id"], cu["company_id"])

    to_update = []
    for emp in Employee.objects.filter(company__isnull=True).only("id", "user_id"):
        company_id = user_to_company.get(emp.user_id)
        if company_id is not None:
            emp.company_id = company_id
            to_update.append(emp)

    if to_update:
        Employee.objects.bulk_update(to_update, ["company"], batch_size=500)


def noop_reverse(apps, schema_editor):
    # Non-destructive: leave the backfilled values in place on reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0066_employee_company"),
    ]

    operations = [
        migrations.RunPython(backfill_company, noop_reverse),
    ]
