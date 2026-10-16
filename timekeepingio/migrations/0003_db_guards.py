"""Attendance's invariants in the database itself (attendance backend spec
§3.3, §10 invariants 1 and 8), not only in the application. Postgres only --
the test database (SQLite) relies on the model-level guards.

- A punch is never updated or deleted (the spec's `DO INSTEAD NOTHING`,
  refused loudly instead of silently); the audit likewise.
- Shift assignments for one employee never overlap: a GiST exclusion over
  the effective window.
"""

from django.db import migrations

UP = """
CREATE OR REPLACE FUNCTION timekeepingio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted. Correct a day with an adjustment.',
    TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS timekeepingio_punch_append_only ON timekeepingio_punch;
CREATE TRIGGER timekeepingio_punch_append_only BEFORE UPDATE OR DELETE ON timekeepingio_punch
  FOR EACH ROW EXECUTE FUNCTION timekeepingio_append_only();
DROP TRIGGER IF EXISTS timekeepingio_attendanceaudit_append_only ON timekeepingio_attendanceaudit;
CREATE TRIGGER timekeepingio_attendanceaudit_append_only BEFORE UPDATE OR DELETE ON timekeepingio_attendanceaudit
  FOR EACH ROW EXECUTE FUNCTION timekeepingio_append_only();

CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE timekeepingio_shiftassignment DROP CONSTRAINT IF EXISTS timekeepingio_assignment_no_overlap;
ALTER TABLE timekeepingio_shiftassignment ADD CONSTRAINT timekeepingio_assignment_no_overlap
  EXCLUDE USING gist (employee_id WITH =,
                      daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&);
"""
DOWN = """
ALTER TABLE timekeepingio_shiftassignment DROP CONSTRAINT IF EXISTS timekeepingio_assignment_no_overlap;
DROP TRIGGER IF EXISTS timekeepingio_punch_append_only ON timekeepingio_punch;
DROP TRIGGER IF EXISTS timekeepingio_attendanceaudit_append_only ON timekeepingio_attendanceaudit;
DROP FUNCTION IF EXISTS timekeepingio_append_only();
"""


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UP, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [("timekeepingio", "0002_attendance_permissions")]

    operations = [migrations.RunPython(up, down)]
