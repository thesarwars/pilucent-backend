"""The eight ID card permissions (§6), created now and added to the `admin`
group -- the role builder's source -- and the database guards (§8): the
audit is append-only and a card is never deleted, even by raw SQL or a
cascade. Postgres only; the test database relies on the model guards."""

from django.db import migrations

PERMISSIONS = (
    ("issue_cards", "Can create and issue ID cards"),
    ("revoke_cards", "Can revoke, report lost and replace ID cards"),
    ("edit_card_templates", "Can design ID card templates"),
    ("publish_card_templates", "Can publish an ID card template version"),
    ("print_cards", "Can submit ID card print jobs"),
    ("override_card_print", "Can print ID cards that carry warnings"),
    ("manage_card_photos", "Can upload, crop and replace ID card photos"),
    ("manage_card_fields", "Can manage ID card custom fields and what the verification page shows"),
)

GUARDS = """
CREATE OR REPLACE FUNCTION idcardio_audit_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (to_jsonb(NEW) - 'card_id' - 'template_id' - 'job_id')
                        = (to_jsonb(OLD) - 'card_id' - 'template_id' - 'job_id') THEN
    RETURN NEW;  -- a SET NULL from a parent row, nothing else
  END IF;
  RAISE EXCEPTION 'The card audit is append-only: row % is not changed or deleted.', OLD.id;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS idcardio_audit_guard ON idcardio_cardaudit;
CREATE TRIGGER idcardio_audit_guard BEFORE UPDATE OR DELETE ON idcardio_cardaudit
  FOR EACH ROW EXECUTE FUNCTION idcardio_audit_guard();

CREATE OR REPLACE FUNCTION idcardio_card_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'A card is never deleted (%): revoke it instead.', OLD.card_number;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS idcardio_card_guard ON idcardio_card;
CREATE TRIGGER idcardio_card_guard BEFORE DELETE ON idcardio_card
  FOR EACH ROW EXECUTE FUNCTION idcardio_card_guard();
"""
DOWN = """
DROP TRIGGER IF EXISTS idcardio_audit_guard ON idcardio_cardaudit;
DROP FUNCTION IF EXISTS idcardio_audit_guard();
DROP TRIGGER IF EXISTS idcardio_card_guard ON idcardio_card;
DROP FUNCTION IF EXISTS idcardio_card_guard();
"""


def add_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="idcardio", model="cardaudit")
    perms = [Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
             for code, name in PERMISSIONS]
    admin = Group.objects.filter(name="admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(content_type__app_label="idcardio", codename__in=[c for c, _ in PERMISSIONS]).delete()


def up(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARDS, params=None)


def down(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DOWN, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ("idcardio", "0001_idcards"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(up, down),
    ]
