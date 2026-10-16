"""Salary structures move onto the pay library (3 of 3): structures point
at the library's templates, the per-line base columns go (a line's bases
are read from its component version), and SalaryTemplate is removed."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [("employeeio", "0009_pay_library_copy")]

    operations = [
        migrations.RemoveField(model_name="employeesalarystructure", name="template_version"),
        migrations.RenameField(model_name="employeesalarystructure", old_name="library_template",
                               new_name="template_version"),
        migrations.AlterField(
            model_name="employeesalarystructure",
            name="template_version",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="structures", to="paylibio.structuretemplate"),
        ),
        migrations.RemoveField(model_name="employeesalarycomponent", name="in_ot_base"),
        migrations.RemoveField(model_name="employeesalarycomponent", name="in_pf_base"),
        migrations.RemoveField(model_name="employeesalarycomponent", name="in_gratuity_base"),
        migrations.RemoveField(model_name="employeesalarycomponent", name="in_wages_base"),
        migrations.RemoveField(model_name="employeesalarycomponent", name="in_perquisite_ceiling"),
        migrations.DeleteModel(name="SalaryTemplate"),
    ]
