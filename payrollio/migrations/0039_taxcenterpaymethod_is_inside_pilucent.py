from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("payrollio", "0038_payrolltaxconfig"),
    ]

    operations = [
        migrations.RenameField(
            model_name="taxcenterpaymethod",
            old_name="is_inside_balanzify",
            new_name="is_inside_pilucent",
        ),
    ]
