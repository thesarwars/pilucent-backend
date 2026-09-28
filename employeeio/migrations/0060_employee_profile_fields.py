from django.db import migrations, models

from common.django_rest.helpers.countries import COUNTRIES


class Migration(migrations.Migration):

    dependencies = [
        ("employeeio", "0059_employeeexpensereport_paid_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="first_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="middle_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="last_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="name",
            field=models.CharField(blank=True, max_length=250, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="salutation",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="blood_group",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[
                    ("MALE", "Male"),
                    ("FEMALE", "Female"),
                    ("OTHERS", "Others"),
                ],
                db_index=True,
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="nid_card_no",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="ssn",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="country",
            field=models.CharField(
                blank=True,
                choices=COUNTRIES,
                db_index=True,
                max_length=2,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="description",
            field=models.TextField(blank=True, null=True),
        ),
    ]
