"""The payslip permissions (§7), added to the `admin` group, and the database
guards (§3.2, §3.6, §8). Postgres only; the test database relies on the model
guards.

- An issued document's figures are frozen and it is never deleted; only its
  state advances, it may be linked to a correction and its retention extended.
- A register must match the issued slips it was written from, and is frozen.
- Retention is never shortened. The audit is append-only.
"""

from django.db import migrations

from payslipio.choices import PERMISSIONS

GUARDS = """
CREATE OR REPLACE FUNCTION payslipio_retention_not_shortened() RETURNS trigger AS $$
BEGIN
  IF OLD.retention_until IS NOT NULL
     AND (NEW.retention_until IS NULL OR NEW.retention_until < OLD.retention_until) THEN
    RAISE EXCEPTION 'Retention runs to % and cannot be shortened to %.', OLD.retention_until, NEW.retention_until;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION payslipio_slip_immutable() RETURNS trigger AS $$
BEGIN
  IF OLD.state IN ('ISSUED','DELIVERED','SUPERSEDED') THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Document % is issued and cannot be deleted. Retention runs to %.',
        OLD.document_no, OLD.retention_until;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['state','superseded_by_id','retention_until','updated_at'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','superseded_by_id','retention_until','updated_at']) THEN
      RAISE EXCEPTION 'Document % is issued. A correction is a new document that supersedes it, not an edit.',
        OLD.document_no;
    END IF;
    IF NOT ((OLD.state = 'ISSUED' AND NEW.state IN ('ISSUED','DELIVERED','SUPERSEDED'))
         OR (OLD.state = 'DELIVERED' AND NEW.state IN ('DELIVERED','SUPERSEDED'))
         OR (OLD.state = 'SUPERSEDED' AND NEW.state = 'SUPERSEDED')) THEN
      RAISE EXCEPTION 'Document % is %; it does not go back.', OLD.document_no, OLD.state;
    END IF;
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payslipio_slip_immutable ON payslipio_payslipdocument;
CREATE TRIGGER payslipio_slip_immutable BEFORE UPDATE OR DELETE ON payslipio_payslipdocument
  FOR EACH ROW EXECUTE FUNCTION payslipio_slip_immutable();
DROP TRIGGER IF EXISTS payslipio_slip_retention ON payslipio_payslipdocument;
CREATE TRIGGER payslipio_slip_retention BEFORE UPDATE ON payslipio_payslipdocument
  FOR EACH ROW EXECUTE FUNCTION payslipio_retention_not_shortened();

CREATE OR REPLACE FUNCTION payslipio_register_matches_slips() RETURNS trigger AS $$
DECLARE n INTEGER; s NUMERIC(18,4);
BEGIN
  SELECT COUNT(*), COALESCE(SUM(net_pay),0) INTO n, s FROM payslipio_payslipdocument
   WHERE run_id = NEW.run_id AND state IN ('ISSUED','DELIVERED');
  IF n <> NEW.row_count OR s <> NEW.total_net THEN
    RAISE EXCEPTION 'Register states % rows totalling %, the issued slips are % totalling % — a register that disagrees with the slips is the document an inspector will find.',
      NEW.row_count, NEW.total_net, n, s;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payslipio_register_matches ON payslipio_wagesregister;
CREATE TRIGGER payslipio_register_matches BEFORE INSERT ON payslipio_wagesregister
  FOR EACH ROW EXECUTE FUNCTION payslipio_register_matches_slips();

CREATE OR REPLACE FUNCTION payslipio_register_frozen() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'The register for % cannot be deleted. Retention runs to %.', OLD.period, OLD.retention_until;
  END IF;
  IF (to_jsonb(NEW) - ARRAY['retention_until','updated_at']) IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['retention_until','updated_at']) THEN
    RAISE EXCEPTION 'A wages register is generated once; only its retention may be extended.';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payslipio_register_frozen ON payslipio_wagesregister;
CREATE TRIGGER payslipio_register_frozen BEFORE UPDATE OR DELETE ON payslipio_wagesregister
  FOR EACH ROW EXECUTE FUNCTION payslipio_register_frozen();
DROP TRIGGER IF EXISTS payslipio_register_retention ON payslipio_wagesregister;
CREATE TRIGGER payslipio_register_retention BEFORE UPDATE ON payslipio_wagesregister
  FOR EACH ROW EXECUTE FUNCTION payslipio_retention_not_shortened();

CREATE OR REPLACE FUNCTION payslipio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted.', TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payslipio_audit_append_only ON payslipio_payslipaudit;
CREATE TRIGGER payslipio_audit_append_only BEFORE UPDATE OR DELETE ON payslipio_payslipaudit
  FOR EACH ROW EXECUTE FUNCTION payslipio_append_only();
"""
DOWN = """
DROP TRIGGER IF EXISTS payslipio_slip_immutable ON payslipio_payslipdocument;
DROP TRIGGER IF EXISTS payslipio_slip_retention ON payslipio_payslipdocument;
DROP FUNCTION IF EXISTS payslipio_slip_immutable();
DROP TRIGGER IF EXISTS payslipio_register_matches ON payslipio_wagesregister;
DROP FUNCTION IF EXISTS payslipio_register_matches_slips();
DROP TRIGGER IF EXISTS payslipio_register_frozen ON payslipio_wagesregister;
DROP TRIGGER IF EXISTS payslipio_register_retention ON payslipio_wagesregister;
DROP FUNCTION IF EXISTS payslipio_register_frozen();
DROP FUNCTION IF EXISTS payslipio_retention_not_shortened();
DROP TRIGGER IF EXISTS payslipio_audit_append_only ON payslipio_payslipaudit;
DROP FUNCTION IF EXISTS payslipio_append_only();
"""


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="payslipio", model="payslipdocument")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="payslipio", codename__in=[c for c, _ in PERMISSIONS]).delete()


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ("payslipio", "0001_payslips"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(up, down),
    ]
