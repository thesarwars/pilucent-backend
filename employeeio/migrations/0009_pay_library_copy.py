"""Salary structures move onto the pay library (2 of 3): the copy.

- Each company's SalaryTemplate rows become row-based StructureTemplates:
  one version per dated row, in date order, the older superseded by the
  newer; an inactive row is archived. Structures point at the copy.
- Every existing line pins component version 1. The five per-line base
  booleans go: a line's bases are read from the component version it pins,
  and the seeded version 1 carries exactly the flags those columns held
  (basic in OT, PF, gratuity and wages; the allowances in wages and the
  perquisite ceiling), so no line's bases change.
- SalaryTemplate is removed.
"""

from django.db import migrations


COLUMNS = (("BASIC", "PCT_OF_GROSS", "basic_pct"), ("HRA", "PCT_OF_BASIC", "hr_pct_of_basic"),
           ("MED", "PCT_OF_GROSS", "med_pct"), ("CONV", "PCT_OF_GROSS", "conv_pct"))


def copy_templates(apps, schema_editor):
    SalaryTemplate = apps.get_model("employeeio", "SalaryTemplate")
    StructureTemplate = apps.get_model("paylibio", "StructureTemplate")
    Row = apps.get_model("paylibio", "StructureTemplateRow")
    Structure = apps.get_model("employeeio", "EmployeeSalaryStructure")
    mapping = {}
    by_code = {}
    for t in SalaryTemplate.objects.order_by("company_id", "code", "effective_from", "id"):
        by_code.setdefault((t.company_id, t.code), []).append(t)
    for (company_id, code), versions in by_code.items():
        previous = None
        for n, t in enumerate(versions, start=1):
            new = StructureTemplate.objects.create(
                company_id=company_id, code=code, version=n, name=t.label, name_bn=t.label_bn, mode="GROSS_DOWN",
                note=t.note, note_bn=t.note_bn, balancing_code=t.balancing_component,
                status="PUBLISHED" if t.is_active else "ARCHIVED", display_order=t.display_order,
                effective_from=t.effective_from, created_by_id=t.created_by_id)
            for i, (comp, basis, attr) in enumerate(COLUMNS):
                value = getattr(t, attr)
                if value:
                    Row.objects.create(template=new, component_code=comp, basis=basis, value=value, display_order=i)
            if previous is not None:
                previous.superseded_by = new
                previous.save(update_fields=["superseded_by"])
            previous = new
            mapping[t.pk] = new.pk
    for s in Structure.objects.exclude(template_version__isnull=True).only("id", "template_version_id"):
        s.library_template_id = mapping.get(s.template_version_id)
        s.save(update_fields=["library_template"])


class Migration(migrations.Migration):

    dependencies = [("employeeio", "0008_pay_library")]

    operations = [migrations.RunPython(copy_templates, migrations.RunPython.noop)]
