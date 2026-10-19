"""The intake permissions (§8), created now and added to the `admin` group
-- the role builder's source -- and the database guards (§3.4, §6.3, §9).
Postgres only; the test database relies on the model guards.

- A raw punch is never deleted, its timestamp, raw row and batch never
  change, and its employee is set once, from none (the re-link).
- The intake audit is append-only; a batch is never deleted.
- The register never takes a punch dated in a locked month, whatever path
  wrote it: validation is the user's path, this is the floor.
"""

from django.db import migrations

PERMISSIONS = (
    ("import_attendance", "Can upload, parse and validate attendance imports"),
    ("process_attendance_import", "Can process an attendance import into the register"),
    ("override_attendance_import", "Can process an attendance import over its warnings"),
    ("reverse_attendance_import", "Can reverse a processed attendance import"),
    ("map_device_users", "Can create and close device ID mappings"),
    ("advance_attendance_period", "Can move an attendance period to processing and review"),
    ("manage_device_profiles", "Can manage attendance device profiles"),
)

GUARDS = """
CREATE OR REPLACE FUNCTION intakeio_punch_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A raw punch cannot be deleted. Reverse the batch.';
  END IF;
  IF (OLD.punched_at, OLD.punch_date, OLD.punch_time, OLD.device_user_id, OLD.device_label, OLD.raw_row,
      OLD.source_row, OLD.batch_id, OLD.direction, OLD.source_timezone)
     IS DISTINCT FROM
     (NEW.punched_at, NEW.punch_date, NEW.punch_time, NEW.device_user_id, NEW.device_label, NEW.raw_row,
      NEW.source_row, NEW.batch_id, NEW.direction, NEW.source_timezone) THEN
    RAISE EXCEPTION 'A raw punch cannot be edited. Record an adjustment in the register (punch %).', OLD.id;
  END IF;
  IF OLD.employee_id IS NOT NULL AND NEW.employee_id IS DISTINCT FROM OLD.employee_id THEN
    RAISE EXCEPTION 'A punch attributed to an employee is never reattributed (punch %).', OLD.id;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS intakeio_punch_guard ON intakeio_intakepunch;
CREATE TRIGGER intakeio_punch_guard BEFORE UPDATE OR DELETE ON intakeio_intakepunch
  FOR EACH ROW EXECUTE FUNCTION intakeio_punch_guard();

CREATE OR REPLACE FUNCTION intakeio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted.', TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS intakeio_audit_append_only ON intakeio_intakeaudit;
CREATE TRIGGER intakeio_audit_append_only BEFORE UPDATE OR DELETE ON intakeio_intakeaudit
  FOR EACH ROW EXECUTE FUNCTION intakeio_append_only();

CREATE OR REPLACE FUNCTION intakeio_batch_no_delete() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Import batch % is never deleted: reverse it.', OLD.reference;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS intakeio_batch_no_delete ON intakeio_importbatch;
CREATE TRIGGER intakeio_batch_no_delete BEFORE DELETE ON intakeio_importbatch
  FOR EACH ROW EXECUTE FUNCTION intakeio_batch_no_delete();

CREATE OR REPLACE FUNCTION timekeepingio_punch_not_in_locked_period() RETURNS trigger AS $$
DECLARE st TEXT;
BEGIN
  SELECT status INTO st FROM timekeepingio_attendanceperiod
   WHERE site_id = NEW.site_id AND period_month = date_trunc('month', NEW.business_date)::date;
  IF st = 'LOCKED' THEN
    RAISE EXCEPTION 'Punch dated % falls in a locked period.', NEW.business_date;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS timekeepingio_punch_not_in_locked_period ON timekeepingio_punch;
CREATE TRIGGER timekeepingio_punch_not_in_locked_period BEFORE INSERT ON timekeepingio_punch
  FOR EACH ROW EXECUTE FUNCTION timekeepingio_punch_not_in_locked_period();
"""
DOWN = """
DROP TRIGGER IF EXISTS intakeio_punch_guard ON intakeio_intakepunch;
DROP FUNCTION IF EXISTS intakeio_punch_guard();
DROP TRIGGER IF EXISTS intakeio_audit_append_only ON intakeio_intakeaudit;
DROP FUNCTION IF EXISTS intakeio_append_only();
DROP TRIGGER IF EXISTS intakeio_batch_no_delete ON intakeio_importbatch;
DROP FUNCTION IF EXISTS intakeio_batch_no_delete();
DROP TRIGGER IF EXISTS timekeepingio_punch_not_in_locked_period ON timekeepingio_punch;
DROP FUNCTION IF EXISTS timekeepingio_punch_not_in_locked_period();
"""


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="intakeio", model="intakeaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="intakeio", codename__in=[c for c, _ in PERMISSIONS]).delete()


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ("intakeio", "0001_intake"),
        ("timekeepingio", "0004_intake_void_and_period"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(up, down),
    ]
