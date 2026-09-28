from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payrollio", "0035_rename_payrollstatetaxinfosetting_ein_to_win"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="payrollfederaltaxinfosettingitems",
            constraint=models.UniqueConstraint(
                condition=models.Q(("tax_form__isnull", False)),
                fields=("payroll_federal_tax_info", "tax_form", "effective_date"),
                name="uniq_federal_tax_item_form_effective_date",
            ),
        ),
    ]
