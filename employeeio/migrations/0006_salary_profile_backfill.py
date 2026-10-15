"""Backfill for the salary profile (docs/backend/salary-profile.md).

- Components on file get their measured percentages, basis text and the five
  base flags. No template percentage is recorded for them: they were built on
  the retired std/classic templates or the RMG gazette, so there is nothing
  to measure an override against, and none is invented.
- The three salary permissions are created now (Django would otherwise only
  create them after migrating) and added to the `admin` group, the source of
  the role builder's available permissions.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

PERMISSIONS = (
    ("view_salary_figures", "Can view salary figures"),
    ("write_salary", "Can assign, revise and override salary structures"),
    ("approve_salary", "Can approve a salary revision someone else raised"),
)
ONE_DP = Decimal("0.1")


def _pct(amount, whole):
    if not whole:
        return None
    return (Decimal(amount) * 100 / Decimal(whole)).quantize(ONE_DP, rounding=ROUND_HALF_UP)


def _text(value):
    text = f"{value:f}"
    return text[:-2] if text.endswith(".0") else text


def backfill_components(apps, schema_editor):
    Structure = apps.get_model("employeeio", "EmployeeSalaryStructure")
    Component = apps.get_model("employeeio", "EmployeeSalaryComponent")
    for structure in Structure.objects.all().iterator():
        lines = list(Component.objects.filter(structure=structure))
        gross = sum((c.amount for c in lines), Decimal(0))
        basic = sum((c.amount for c in lines if c.code == "BASIC"), Decimal(0))
        for c in lines:
            of_basic = c.code == "HRA"
            c.effective_pct = _pct(c.amount, basic if of_basic else gross)
            if not c.basis_text and c.effective_pct is not None:
                c.basis_text = f"{_text(c.effective_pct)}% of {'basic' if of_basic else 'gross'}"
            is_basic = c.code == "BASIC"
            c.in_ot_base = c.in_pf_base = c.in_gratuity_base = is_basic
            c.in_wages_base = True
            c.in_perquisite_ceiling = not is_basic
            c.save(update_fields=["effective_pct", "basis_text", "in_ot_base", "in_pf_base", "in_gratuity_base",
                                  "in_wages_base", "in_perquisite_ceiling"])


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="employeeio", model="salaryaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="employeeio", codename__in=[c for c, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0005_salary_profile"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(backfill_components, migrations.RunPython.noop),
        migrations.RunPython(add_permissions, remove_permissions),
    ]
