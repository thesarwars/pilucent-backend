import dirtyfields.dirtyfields
import django.db.models.deletion
import uuid
from django.db import migrations, models


def backfill_subscription_price_currency(apps, schema_editor):
    SubscriptionPrice = apps.get_model("subscriptionio", "SubscriptionPrice")
    for price in SubscriptionPrice.objects.select_related("subscription").iterator():
        subscription_currency = price.subscription.currency or "USD"
        if price.currency != subscription_currency:
            price.currency = subscription_currency
            price.save(update_fields=["currency"])


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "__first__"),
        ("employeeio", "__first__"),
        ("subscriptionio", "0015_lifecycle_phase5"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionprice",
            name="currency",
            field=models.CharField(default="USD", max_length=50),
        ),
        migrations.AddField(
            model_name="subscriptionprice",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(backfill_subscription_price_currency, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="subscriptionprice",
            unique_together={("subscription", "billing_frequency", "currency")},
        ),
        migrations.AddField(
            model_name="subscriptioninvoice",
            name="is_manual",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="subscriptioninvoice",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="SubscriptionContract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uid", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("title", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("currency", models.CharField(default="USD", max_length=20)),
                ("custom_price", models.DecimalField(blank=True, decimal_places=3, max_digits=19, null=True)),
                ("custom_discount", models.DecimalField(blank=True, decimal_places=3, max_digits=19, null=True)),
                ("discount_kind", models.CharField(choices=[("FLAT", "Flat"), ("PERCENTAGE", "Percentage")], default="FLAT", max_length=20)),
                ("employee_limit_override", models.PositiveIntegerField(blank=True, null=True)),
                ("user_limit_override", models.PositiveIntegerField(blank=True, null=True)),
                ("is_manual_billing", models.BooleanField(default=False)),
                ("contract_start", models.DateTimeField()),
                ("contract_end", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("EXPIRED", "Expired"), ("CANCELED", "Canceled")], default="ACTIVE", max_length=20)),
                ("notes", models.TextField(blank=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subscription_contracts", to="companyio.company")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="employeeio.employee")),
                ("plan_version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="contracts", to="subscriptionio.planversion")),
                ("subscription_price", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="contracts", to="subscriptionio.subscriptionprice")),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="PlanMigrationJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uid", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("title", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("RUNNING", "Running"), ("COMPLETED", "Completed"), ("FAILED", "Failed")], default="PENDING", max_length=20)),
                ("grandfather_existing", models.BooleanField(default=True)),
                ("dry_run", models.BooleanField(default=True)),
                ("total_companies", models.PositiveIntegerField(default=0)),
                ("migrated_count", models.PositiveIntegerField(default=0)),
                ("failed_count", models.PositiveIntegerField(default=0)),
                ("skipped_count", models.PositiveIntegerField(default=0)),
                ("error_log", models.JSONField(blank=True, default=list)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="employeeio.employee")),
                ("source_plan_version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="source_migration_jobs", to="subscriptionio.planversion")),
                ("source_subscription", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="source_migration_jobs", to="subscriptionio.subscription")),
                ("target_plan_version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="target_migration_jobs", to="subscriptionio.planversion")),
                ("target_subscription", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="target_migration_jobs", to="subscriptionio.subscription")),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="PlanMigrationRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uid", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("title", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("SUCCESS", "Success"), ("FAILED", "Failed"), ("SKIPPED", "Skipped")], default="SUCCESS", max_length=20)),
                ("message", models.TextField(blank=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plan_migration_records", to="companyio.company")),
                ("company_subscription", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="subscriptionio.companysubscription")),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="records", to="subscriptionio.planmigrationjob")),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
    ]
