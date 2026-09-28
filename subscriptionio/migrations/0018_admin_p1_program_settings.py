import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptionio", "0017_alter_field_choices_alignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="referralredemption",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                ],
                db_index=True,
                default="APPROVED",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="SubscriptionProgramSettings",
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
                    "referral_reward_amount",
                    models.DecimalField(decimal_places=2, default=25, max_digits=12),
                ),
                ("referral_max_per_month", models.PositiveIntegerField(blank=True, null=True)),
                ("referral_require_approval", models.BooleanField(default=False)),
                ("referral_program_active", models.BooleanField(default=True)),
                ("trial_default_days", models.PositiveIntegerField(default=14)),
                ("trial_card_required", models.BooleanField(default=False)),
                ("trial_auto_convert", models.BooleanField(default=True)),
                ("trial_reminder_days", models.JSONField(default=list)),
                ("trial_max_extension_days", models.PositiveIntegerField(default=7)),
                ("trial_one_per_domain", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name_plural": "Subscription program settings",
            },
        ),
    ]
