from django.db import migrations


class Migration(migrations.Migration):
    """Drop the deprecated `Role` and `CompanyRoleAndPermission` models.

    Both have been marked deprecated in adminio/models.py for some time. They were
    superseded by `CompanyRole` (which now carries kind/is_system/status as of
    0004_companyrole_kind_is_system_and_more) and the `CompanyUser.roles` M2M
    introduced in companyio 0017_companyuser_roles.
    """

    dependencies = [
        ("adminio", "0004_companyrole_kind_is_system_and_more"),
        ("companyio", "0019_remove_companyuser_role"),
    ]

    operations = [
        migrations.DeleteModel(name="CompanyRoleAndPermission"),
        migrations.DeleteModel(name="Role"),
    ]
