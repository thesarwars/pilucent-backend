"""Dearness allowance is in the s.108 overtime base: overtime is paid on
basic plus DA. The first seed left it out; version 1 of DA is corrected in
place (setting a base is allowed -- only unsetting a locked one is not), and
from now on the flag is locked, statutory, citing s.108."""

from django.db import migrations


def fix(apps, schema_editor):
    PayComponent = apps.get_model("paylibio", "PayComponent")
    PayComponent.objects.filter(code="DA", version=1, in_ot_base_s108=False).update(
        in_ot_base_s108=True, is_statutory=True,
        statutory_basis="Bangladesh Labour Act 2006, s.108 (overtime on basic and dearness allowance)",
        locked_flags=["in_ot_base_s108"])


class Migration(migrations.Migration):

    dependencies = [("paylibio", "0002_permissions_guards")]

    operations = [migrations.RunPython(fix, migrations.RunPython.noop)]
