"""The ledger's immutability in the database itself (backend spec §3.4, §6
invariants 2-3), not only in the application: a raw SQL update or delete is
refused too. Postgres only -- the test database (SQLite) relies on the
model-level guards.

The spec's `DO INSTEAD NOTHING` rule would make a delete silently succeed;
these triggers refuse it loudly instead, so a cascade that would remove
ledger history fails rather than half-happening.
"""

from django.db import migrations

LEDGER = """
CREATE OR REPLACE FUNCTION leaveledgerio_ledger_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'The leave ledger is append-only: entry % is not deleted. Correct it with a reversal.', OLD.id;
  END IF;
  IF OLD.reversed_by_id IS NULL AND NEW.reversed_by_id IS NOT NULL
     AND (to_jsonb(NEW) - 'reversed_by_id') = (to_jsonb(OLD) - 'reversed_by_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'The leave ledger is append-only: only reversed_by_id may change, once, from null (entry %).', OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS leaveledgerio_ledger_guard ON leaveledgerio_ledgerentry;
CREATE TRIGGER leaveledgerio_ledger_guard BEFORE UPDATE OR DELETE ON leaveledgerio_ledgerentry
  FOR EACH ROW EXECUTE FUNCTION leaveledgerio_ledger_guard();

CREATE OR REPLACE FUNCTION leaveledgerio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted.', TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
"""
APPEND_ONLY = ("leaveledgerio_leaveaudit", "leaveledgerio_maternityevent", "leaveledgerio_statementissue")
DOWN = """
DROP TRIGGER IF EXISTS leaveledgerio_ledger_guard ON leaveledgerio_ledgerentry;
DROP FUNCTION IF EXISTS leaveledgerio_ledger_guard();
""" + "".join(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};\n" for t in APPEND_ONLY) + \
    "DROP FUNCTION IF EXISTS leaveledgerio_append_only();\n"


def up(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    sql = LEDGER + "".join(
        f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};\n"
        f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION leaveledgerio_append_only();\n" for t in APPEND_ONLY)
    schema_editor.execute(sql, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [("leaveledgerio", "0003_maternity_statements_events")]

    operations = [migrations.RunPython(up, down)]
