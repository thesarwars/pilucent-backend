"""The payroll-settings permissions (§7), added to the `admin` group, and the
database guards (§5). Postgres only; the test database relies on the model
and service guards.

- No two governing (ACTIVE or SUPERSEDED) periods of one election overlap
  for one scope (invariant 1); likewise schemes (2). A site row and the
  company row are different scopes: the site's overrides by precedence.
- Bonus bands are contiguous and cover months 0 to 11 (invariant 5).
- An election is never updated in place: only its lifecycle columns move.
  It is never deleted. The audit is append-only.
"""

from django.db import migrations

PERMISSIONS = (
    ("view_payroll_settings", "Can view payroll settings"),
    ("preview_payroll_election", "Can run a payroll election consequence preview"),
    ("write_payroll_election", "Can elect or propose a payroll election"),
    ("approve_payroll_election", "Can approve a payroll election (not one they proposed)"),
    ("write_payroll_scheme", "Can enable and configure statutory schemes"),
    ("write_pay_schedule", "Can set the pay frequency, cut-off and payment day"),
    ("map_payroll_gl", "Can map statutory schemes to GL accounts"),
)

GUARDS = """
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE paysetio_payrollelection DROP CONSTRAINT IF EXISTS paysetio_no_overlapping_elections;
ALTER TABLE paysetio_payrollelection ADD CONSTRAINT paysetio_no_overlapping_elections
  EXCLUDE USING gist (
    company_id WITH =,
    COALESCE(site_id, 0) WITH =,
    election_key WITH =,
    daterange(effective_from, effective_to, '[]') WITH &&
  ) WHERE (status IN ('ACTIVE', 'SUPERSEDED'));

ALTER TABLE paysetio_statutoryscheme DROP CONSTRAINT IF EXISTS paysetio_no_overlapping_schemes;
ALTER TABLE paysetio_statutoryscheme ADD CONSTRAINT paysetio_no_overlapping_schemes
  EXCLUDE USING gist (
    company_id WITH =,
    COALESCE(site_id, 0) WITH =,
    scheme_code WITH =,
    daterange(effective_from, effective_to, '[]') WITH &&
  ) WHERE (status IN ('ACTIVE', 'SUPERSEDED'));

ALTER TABLE paysetio_payschedule DROP CONSTRAINT IF EXISTS paysetio_no_overlapping_schedules;
ALTER TABLE paysetio_payschedule ADD CONSTRAINT paysetio_no_overlapping_schedules
  EXCLUDE USING gist (
    company_id WITH =,
    COALESCE(site_id, 0) WITH =,
    daterange(effective_from, effective_to, '[]') WITH &&
  ) WHERE (status IN ('ACTIVE', 'SUPERSEDED'));

CREATE OR REPLACE FUNCTION paysetio_validate_bonus_bands() RETURNS trigger AS $$
DECLARE prev INT := -1; b JSONB;
BEGIN
  IF NEW.election_key <> 'festival_bonus_policy' OR NEW.value_text IS DISTINCT FROM 'BANDED' THEN
    RETURN NEW;
  END IF;
  FOR b IN SELECT * FROM jsonb_array_elements(NEW.value_json::jsonb->'bands') LOOP
    IF (b->>'fromMonths')::INT <> prev + 1 THEN
      RAISE EXCEPTION 'Bonus bands must be contiguous — a gap or overlap at month %', (b->>'fromMonths')::INT;
    END IF;
    IF (b->>'pct')::NUMERIC < 0 OR (b->>'pct')::NUMERIC > 100 THEN
      RAISE EXCEPTION 'A bonus band percentage must be 0 to 100, got %', b->>'pct';
    END IF;
    prev := (b->>'toMonths')::INT;
  END LOOP;
  IF prev <> 11 THEN
    RAISE EXCEPTION 'Bonus bands must cover months 0 to 11, last band ends at %', prev;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS paysetio_election_bands_valid ON paysetio_payrollelection;
CREATE TRIGGER paysetio_election_bands_valid BEFORE INSERT OR UPDATE ON paysetio_payrollelection
  FOR EACH ROW EXECUTE FUNCTION paysetio_validate_bonus_bands();

CREATE OR REPLACE FUNCTION paysetio_election_immutable() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'An election is never deleted: row % is the record of what the company elected.', OLD.id;
  END IF;
  IF (to_jsonb(NEW) - ARRAY['status','effective_to','approved_by_id','approved_by_name','approved_at',
                            'rejected_reason','updated_at'])
     IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['status','effective_to','approved_by_id','approved_by_name','approved_at',
                            'rejected_reason','updated_at']) THEN
    RAISE EXCEPTION 'An election is never updated in place (row %). Elect again from a date instead.', OLD.id;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS paysetio_election_immutable ON paysetio_payrollelection;
CREATE TRIGGER paysetio_election_immutable BEFORE UPDATE OR DELETE ON paysetio_payrollelection
  FOR EACH ROW EXECUTE FUNCTION paysetio_election_immutable();

CREATE OR REPLACE FUNCTION paysetio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted.', TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS paysetio_audit_append_only ON paysetio_settingsaudit;
CREATE TRIGGER paysetio_audit_append_only BEFORE UPDATE OR DELETE ON paysetio_settingsaudit
  FOR EACH ROW EXECUTE FUNCTION paysetio_append_only();
"""
DOWN = """
ALTER TABLE paysetio_payrollelection DROP CONSTRAINT IF EXISTS paysetio_no_overlapping_elections;
ALTER TABLE paysetio_statutoryscheme DROP CONSTRAINT IF EXISTS paysetio_no_overlapping_schemes;
ALTER TABLE paysetio_payschedule DROP CONSTRAINT IF EXISTS paysetio_no_overlapping_schedules;
DROP TRIGGER IF EXISTS paysetio_election_bands_valid ON paysetio_payrollelection;
DROP FUNCTION IF EXISTS paysetio_validate_bonus_bands();
DROP TRIGGER IF EXISTS paysetio_election_immutable ON paysetio_payrollelection;
DROP FUNCTION IF EXISTS paysetio_election_immutable();
DROP TRIGGER IF EXISTS paysetio_audit_append_only ON paysetio_settingsaudit;
DROP FUNCTION IF EXISTS paysetio_append_only();
"""


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="paysetio", model="settingsaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="paysetio", codename__in=[c for c, _ in PERMISSIONS]).delete()


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ("paysetio", "0001_payroll_settings"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(up, down),
    ]
