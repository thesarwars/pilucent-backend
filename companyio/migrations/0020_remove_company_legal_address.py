# Generated manually for primary tax onboarding

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "0019_remove_companyuser_role"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="company",
            name="legal_address",
        ),
        migrations.RemoveField(
            model_name="historicalcompany",
            name="legal_address",
        ),
    ]
