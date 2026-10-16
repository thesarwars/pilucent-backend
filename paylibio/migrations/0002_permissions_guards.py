"""The library permissions (§7), created now and added to the `admin` group,
and the database guards (§3.3, §9): a locked flag may be set, never unset;
the library audit is append-only. Postgres only; the test database relies
on the model guards."""

from django.db import migrations

PERMISSIONS = (
    ("edit_pay_components", "Can edit pay components (name, calculation)"),
    ("change_component_flags", "Can change a pay component's base flags"),
    ("edit_structure_templates", "Can draft structure templates"),
    ("publish_structure_templates", "Can publish a structure template version"),
    ("preview_bulk_revision", "Can preview a bulk salary revision"),
    ("apply_bulk_revision", "Can apply a bulk salary revision"),
    ("map_gl_accounts", "Can map pay components to GL accounts"),
    ("manage_payroll_policy", "Can set the company floor and provident fund rates"),
)

GUARDS = """
CREATE OR REPLACE FUNCTION paylibio_locked_flags() RETURNS trigger AS $$
DECLARE f TEXT;
BEGIN
  IF OLD.locked_flags IS NULL THEN RETURN NEW; END IF;
  FOR f IN SELECT jsonb_array_elements_text(OLD.locked_flags::jsonb) LOOP
    IF to_jsonb(OLD)->>f = 'true' AND to_jsonb(NEW)->>f = 'false' THEN
      RAISE EXCEPTION '% is statutory — % cannot be unset. Change it in the rule book, not in company data.',
        OLD.name, f;
    END IF;
  END LOOP;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS paylibio_locked_flags ON paylibio_paycomponent;
CREATE TRIGGER paylibio_locked_flags BEFORE UPDATE ON paylibio_paycomponent
  FOR EACH ROW EXECUTE FUNCTION paylibio_locked_flags();

CREATE OR REPLACE FUNCTION paylibio_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: row % is not changed or deleted.', TG_TABLE_NAME, OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS paylibio_audit_append_only ON paylibio_libraryaudit;
CREATE TRIGGER paylibio_audit_append_only BEFORE UPDATE OR DELETE ON paylibio_libraryaudit
  FOR EACH ROW EXECUTE FUNCTION paylibio_append_only();
"""
DOWN = """
DROP TRIGGER IF EXISTS paylibio_locked_flags ON paylibio_paycomponent;
DROP FUNCTION IF EXISTS paylibio_locked_flags();
DROP TRIGGER IF EXISTS paylibio_audit_append_only ON paylibio_libraryaudit;
DROP FUNCTION IF EXISTS paylibio_append_only();
"""


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="paylibio", model="libraryaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="paylibio", codename__in=[c for c, _ in PERMISSIONS]).delete()


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ("paylibio", "0001_paylib"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(up, down),
    ]
