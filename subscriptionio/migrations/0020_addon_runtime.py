import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "__first__"),
        ("subscriptionio", "0019_subscription_addon_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlanAddOn",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(
                        db_index=True, default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "availability",
                    models.CharField(
                        choices=[
                            ("OPTIONAL", "Optional"),
                            ("REQUIRED", "Required"),
                            ("UNAVAILABLE", "Unavailable"),
                        ],
                        default="OPTIONAL",
                        max_length=20,
                    ),
                ),
                (
                    "add_on",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_links",
                        to="subscriptionio.subscriptionaddon",
                    ),
                ),
                (
                    "plan_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_addons",
                        to="subscriptionio.planversion",
                    ),
                ),
            ],
            options={
                "unique_together": {("plan_version", "add_on")},
            },
        ),
        migrations.CreateModel(
            name="CompanyAddOn",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(
                        db_index=True, default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("CANCELED", "Canceled"),
                        ],
                        db_index=True,
                        default="ACTIVE",
                        max_length=20,
                    ),
                ),
                ("quantity", models.PositiveIntegerField(default=1)),
                (
                    "unit_price",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                (
                    "stripe_subscription_item_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "add_on",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="company_addons",
                        to="subscriptionio.subscriptionaddon",
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_addons",
                        to="companyio.company",
                    ),
                ),
                (
                    "company_subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="addons",
                        to="subscriptionio.companysubscription",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AlterField(
            model_name="subscriptioninvoiceline",
            name="line_type",
            field=models.CharField(
                choices=[
                    ("BASE", "Base Plan"),
                    ("OVERAGE", "Overage"),
                    ("ADDON", "Add-on"),
                    ("DISCOUNT", "Discount"),
                    ("CREDIT", "Credit"),
                    ("TAX", "Tax"),
                ],
                default="BASE",
                max_length=20,
            ),
        ),
    ]
