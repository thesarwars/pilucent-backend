import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptionio", "0018_admin_p1_program_settings"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionAddOn",
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
                ("title", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.CharField(db_index=True, max_length=50, unique=True)),
                ("description", models.TextField(blank=True)),
                (
                    "pricing_model",
                    models.CharField(
                        choices=[
                            ("RECURRING", "Recurring"),
                            ("ONE_TIME", "One Time"),
                            ("USAGE_BASED", "Usage Based"),
                        ],
                        default="RECURRING",
                        max_length=20,
                    ),
                ),
                (
                    "price",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                (
                    "billing_frequency",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("WEEKLY", "Weekly"),
                            ("MONTHLY", "Monthly"),
                            ("QUARTERLY", " Quarterly"),
                            ("HALF_YEARLY", "Half Yearly"),
                            ("YEARLY", "Yearly"),
                        ],
                        max_length=50,
                        null=True,
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        choices=[
                            ("USD", "USD"),
                            ("EUR", "EUR"),
                            ("GBP", "GBP"),
                            ("CAD", "CAD"),
                            ("AUD", "AUD"),
                            ("BDT", "BDT"),
                        ],
                        default="USD",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("ACTIVE", "Active"),
                            ("DISABLED", "Disabled"),
                        ],
                        db_index=True,
                        default="DRAFT",
                        max_length=20,
                    ),
                ),
                (
                    "metric_code",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("EMPLOYEE", "Employee"),
                            ("USER", "User"),
                            ("BRANCH", "Branch"),
                            ("STORAGE", "Storage"),
                            ("PAYROLL_RUN", "Payroll Run"),
                            ("AI_CREDIT", "AI Credit"),
                        ],
                        max_length=50,
                        null=True,
                    ),
                ),
                ("unit_label", models.CharField(blank=True, max_length=100)),
                (
                    "stripe_price_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "applies_to_subscriptions",
                    models.ManyToManyField(
                        blank=True,
                        related_name="addons",
                        to="subscriptionio.subscription",
                    ),
                ),
            ],
            options={
                "ordering": ("title",),
            },
        ),
    ]
