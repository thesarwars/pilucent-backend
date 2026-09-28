from django.db import migrations


def forward(apps, schema_editor):
    """Copy each CompanyUser.role (FK) into the new CompanyUser.roles (M2M)."""
    CompanyUser = apps.get_model("companyio", "CompanyUser")
    for cu in CompanyUser.objects.exclude(role__isnull=True).only("id", "role_id"):
        cu.roles.add(cu.role_id)


def backward(apps, schema_editor):
    """Best-effort reverse: copy the first role from M2M back into the FK."""
    CompanyUser = apps.get_model("companyio", "CompanyUser")
    for cu in CompanyUser.objects.all():
        first = cu.roles.first()
        if first and not cu.role_id:
            cu.role_id = first.id
            cu.save(update_fields=["role"])


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "0017_companyuser_roles"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
