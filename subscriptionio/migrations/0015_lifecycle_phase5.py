import dirtyfields.dirtyfields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "__first__"),
        ("employeeio", "__first__"),
        ("subscriptionio", "0014_promotions_phase4"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionEvent",
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
                    "event_type",
                    models.CharField(
                        choices=[
                            ("TRIAL_STARTED", "Trial Started"),
                            ("TRIAL_EXPIRED", "Trial Expired"),
                            ("TRIAL_CONVERTED", "Trial Converted"),
                            ("CHECKOUT_COMPLETED", "Checkout Completed"),
                            ("PAYMENT_FAILED", "Payment Failed"),
                            ("PAYMENT_RECOVERED", "Payment Recovered"),
                            ("DUNNING_GRACE", "Dunning Grace"),
                            ("DUNNING_SUSPENDED", "Dunning Suspended"),
                            ("DUNNING_EXPIRED", "Dunning Expired"),
                            ("SUBSCRIPTION_CANCELED", "Subscription Canceled"),
                            ("SUBSCRIPTION_REACTIVATED", "Subscription Reactivated"),
                            ("PLAN_CHANGED", "Plan Changed"),
                        ],
                        db_index=True,
                        max_length=40,
                    ),
                ),
                ("previous_status", models.CharField(blank=True, max_length=50, null=True)),
                ("new_status", models.CharField(blank=True, max_length=50, null=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("SYSTEM", "System"),
                            ("WEBHOOK", "Webhook"),
                            ("API", "API"),
                            ("ADMIN", "Admin"),
                        ],
                        default="SYSTEM",
                        max_length=20,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "stripe_event_id",
                    models.CharField(
                        blank=True, db_index=True, max_length=255, null=True
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="employeeio.employee",
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_events",
                        to="companyio.company",
                    ),
                ),
                (
                    "company_subscription",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="subscriptionio.companysubscription",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="dunning_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="grace_ends_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="suspend_ends_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="canceled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="cancel_at_period_end",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="failed_payment_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
