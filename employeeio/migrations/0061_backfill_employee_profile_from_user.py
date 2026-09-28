from django.db import migrations


PROFILE_FIELDS = (
    "first_name",
    "middle_name",
    "last_name",
    "name",
    "salutation",
    "date_of_birth",
    "blood_group",
    "gender",
    "nid_card_no",
    "ssn",
    "country",
    "description",
)


def forward(apps, schema_editor):
    """Copy each Employee.user.<field> -> Employee.<field> for existing rows.

    This is a one-shot backfill so previously-rendered employee dashboards
    don't go blank after the schema split. After this runs, the two profiles
    diverge: editing the user does not touch the employee, and vice versa.
    """
    Employee = apps.get_model("employeeio", "Employee")
    User = apps.get_model("accounts", "User")

    user_lookup = {u.id: u for u in User.objects.all().only("id", *PROFILE_FIELDS)}

    bulk_updates = []
    for employee in Employee.objects.all().only("id", "user_id", *PROFILE_FIELDS).iterator():
        user = user_lookup.get(employee.user_id)
        if user is None:
            continue
        changed = False
        for field in PROFILE_FIELDS:
            current = getattr(employee, field, None)
            source = getattr(user, field, None)
            if current in (None, "") and source not in (None, ""):
                setattr(employee, field, source)
                changed = True
        if changed:
            bulk_updates.append(employee)

    if bulk_updates:
        Employee.objects.bulk_update(bulk_updates, list(PROFILE_FIELDS), batch_size=500)


def backward(apps, schema_editor):
    """No-op reverse: clearing the new fields is destructive and can't be safely undone."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0060_employee_profile_fields"),
        ("accounts", "0041_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
