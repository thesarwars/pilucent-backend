"""The run payroll permissions (§7), added to the `admin` group, and the
database guards (§3.6, §5). Postgres only; the test database relies on the
model and service guards.

- A line is immutable once its run is approved: only the payment status
  (and when it was paid) still moves. It is never deleted.
- An approved run's stated net reconciles with its lines (§5.1).
- The transition log and the audit are append-only.
"""

from django.db import migrations

PERMISSIONS = (
    ("view_payroll_run", "Can view payroll runs and registers"),
    ("create_payroll_run", "Can open a payroll run"),
    ("compute_payroll_run", "Can compute and recompute a payroll run"),
    ("exclude_payroll_employee", "Can exclude an employee from a payroll run, with a reason"),
    ("override_payroll_ot", "Can type over attendance overtime in a payroll run"),
    ("approve_payroll_run", "Can approve a payroll run (never one they created)"),
    ("instruct_payroll_payment", "Can generate a payment file and instruct payment"),
    ("mark_payroll_paid", "Can mark a payroll line paid or failed"),
    ("release_payslips", "Can release payslips and close a payroll run"),
)

GUARDS = """
CREATE OR REPLACE FUNCTION payrunio_line_mutable() RETURNS trigger AS $$
DECLARE s TEXT;
BEGIN
  SELECT state INTO s FROM payrunio_payrollrun WHERE id = COALESCE(NEW.run_id, OLD.run_id);
  IF s IN ('APPROVED','DISBURSING','PARTIALLY_PAID','PAID','CLOSED') THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Run is % — a line cannot be deleted. Raise an adjustment run.', s;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['payment_status','paid_at','updated_at'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['payment_status','paid_at','updated_at']) THEN
      RAISE EXCEPTION 'Run is % — the figures are fixed. A correction is an adjustment run, not an edit.', s;
    END IF;
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payrunio_line_immutable ON payrunio_payrollrunline;
CREATE TRIGGER payrunio_line_immutable BEFORE UPDATE OR DELETE ON payrunio_payrollrunline
  FOR EACH ROW EXECUTE FUNCTION payrunio_line_mutable();

CREATE OR REPLACE FUNCTION payrunio_run_totals() RETURNS trigger AS $$
DECLARE s NUMERIC(18,4);
BEGIN
  IF NEW.state IN ('APPROVED','DISBURSING','PARTIALLY_PAID','PAID','CLOSED') THEN
    SELECT COALESCE(SUM(net_pay), 0) INTO s FROM payrunio_payrollrunline WHERE run_id = NEW.id AND included;
    IF s <> NEW.total_net THEN
      RAISE EXCEPTION 'Lines total %, the run states % — a register that does not reconcile cannot be paid.',
        s, NEW.total_net;
    END IF;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.state IN ('CLOSED','CANCELLED') AND NEW.state IS DISTINCT FROM OLD.state THEN
    RAISE EXCEPTION 'Run is % — it is terminal and never leaves that state.', OLD.state;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payrunio_run_reconciles ON payrunio_payrollrun;
CREATE TRIGGER payrunio_run_reconciles BEFORE INSERT OR UPDATE ON payrunio_payrollrun
  FOR EACH ROW EXECUTE FUNCTION payrunio_run_totals();

CREATE OR REPLACE FUNCTION payrunio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted.', TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payrunio_transition_append_only ON payrunio_payrollruntransition;
CREATE TRIGGER payrunio_transition_append_only BEFORE UPDATE OR DELETE ON payrunio_payrollruntransition
  FOR EACH ROW EXECUTE FUNCTION payrunio_append_only();
DROP TRIGGER IF EXISTS payrunio_audit_append_only ON payrunio_payrollaudit;
CREATE TRIGGER payrunio_audit_append_only BEFORE UPDATE OR DELETE ON payrunio_payrollaudit
  FOR EACH ROW EXECUTE FUNCTION payrunio_append_only();
"""
DOWN = """
DROP TRIGGER IF EXISTS payrunio_line_immutable ON payrunio_payrollrunline;
DROP FUNCTION IF EXISTS payrunio_line_mutable();
DROP TRIGGER IF EXISTS payrunio_run_reconciles ON payrunio_payrollrun;
DROP FUNCTION IF EXISTS payrunio_run_totals();
DROP TRIGGER IF EXISTS payrunio_transition_append_only ON payrunio_payrollruntransition;
DROP TRIGGER IF EXISTS payrunio_audit_append_only ON payrunio_payrollaudit;
DROP FUNCTION IF EXISTS payrunio_append_only();
"""


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="payrunio", model="payrollrun")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="payrunio", codename__in=[c for c, _ in PERMISSIONS]).delete()


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ("payrunio", "0001_run_payroll"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(up, down),
    ]
