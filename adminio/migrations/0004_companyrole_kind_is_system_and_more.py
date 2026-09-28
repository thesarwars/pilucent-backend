from collections import defaultdict

from django.db import migrations, models


def _dedup_companyrole_names(apps, schema_editor):
    """Rename rows that share the same (company, name) so the upcoming
    unique_together can be applied without an IntegrityError.

    Strategy: keep the oldest (lowest id) row as-is. Rename each subsequent
    duplicate to `<name> (dup N)` where N starts at 2.
    """
    CompanyRole = apps.get_model("adminio", "CompanyRole")
    seen = defaultdict(list)
    for role in CompanyRole.objects.order_by("id").values("id", "company_id", "name"):
        seen[(role["company_id"], role["name"])].append(role["id"])

    for (company_id, name), ids in seen.items():
        if len(ids) <= 1:
            continue
        # Skip the first (keep as-is); rename the rest with an incrementing suffix.
        for i, role_id in enumerate(ids[1:], start=2):
            CompanyRole.objects.filter(pk=role_id).update(name=f"{name} (dup {i})")


def _noop_reverse(apps, schema_editor):
    """No reversal: renames are best-effort and can't be uniquely undone."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("adminio", "0003_companyrole_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyrole",
            name="kind",
            field=models.CharField(
                choices=[("USER", "User"), ("EMPLOYEE", "Employee")],
                db_index=True,
                default="USER",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="companyrole",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Active"),
                    ("INACTIVE", "Inactive"),
                    ("REMOVED", "Removed"),
                ],
                db_index=True,
                default="ACTIVE",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="companyrole",
            name="is_system",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "System roles are seeded per company (admin/user/employee) and cannot be "
                    "deleted or have their name/kind changed."
                ),
            ),
        ),
        migrations.AddField(
            model_name="companyrole",
            name="description",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(_dedup_companyrole_names, _noop_reverse),
        migrations.AlterUniqueTogether(
            name="companyrole",
            unique_together={("company", "name")},
        ),
    ]
