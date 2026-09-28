import dirtyfields.dirtyfields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "__first__"),
        ("subscriptionio", "0012_planlimit_stripe_overage_price_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="UsageCounter",
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
                    "metric_code",
                    models.CharField(
                        choices=[
                            ("EMPLOYEE", "Employee"),
                            ("USER", "User"),
                            ("BRANCH", "Branch"),
                            ("STORAGE", "Storage"),
                            ("PAYROLL_RUN", "Payroll Run"),
                            ("AI_CREDIT", "AI Credit"),
                        ],
                        max_length=50,
                    ),
                ),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("source", models.CharField(default="snapshot", max_length=30)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_counters",
                        to="companyio.company",
                    ),
                ),
            ],
            options={
                "ordering": ("metric_code",),
                "unique_together": {("company", "metric_code")},
            },
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
    ]
