import dirtyfields.dirtyfields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "__first__"),
        ("employeeio", "__first__"),
        ("subscriptionio", "0013_usage_counter_phase3"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionCoupon",
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
                ("code", models.CharField(db_index=True, max_length=50, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("DISABLED", "Disabled"),
                            ("EXPIRED", "Expired"),
                        ],
                        default="ACTIVE",
                        max_length=20,
                    ),
                ),
                (
                    "discount_kind",
                    models.CharField(
                        choices=[("FLAT", "Flat"), ("PERCENTAGE", "Percentage")],
                        default="PERCENTAGE",
                        max_length=20,
                    ),
                ),
                (
                    "discount_value",
                    models.DecimalField(decimal_places=2, max_digits=12),
                ),
                (
                    "max_redemptions",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("redemption_count", models.PositiveIntegerField(default=0)),
                ("max_redemptions_per_company", models.PositiveIntegerField(default=1)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_until", models.DateTimeField(blank=True, null=True)),
                ("is_stackable", models.BooleanField(default=False)),
                (
                    "stripe_coupon_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "applies_to_subscriptions",
                    models.ManyToManyField(
                        blank=True,
                        related_name="coupons",
                        to="subscriptionio.subscription",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="SubscriptionOffer",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("ACTIVE", "Active"),
                            ("EXPIRED", "Expired"),
                        ],
                        default="DRAFT",
                        max_length=20,
                    ),
                ),
                ("is_retention_offer", models.BooleanField(default=False)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_until", models.DateTimeField(blank=True, null=True)),
                (
                    "coupon",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="offers",
                        to="subscriptionio.subscriptioncoupon",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="SubscriptionCredit",
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
                    "initial_amount",
                    models.DecimalField(decimal_places=2, max_digits=12),
                ),
                ("balance", models.DecimalField(decimal_places=2, max_digits=12)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("REFERRAL", "Referral"),
                            ("PROMOTION", "Promotion"),
                            ("ADMIN_ADJUSTMENT", "Admin Adjustment"),
                            ("REFUND", "Refund"),
                        ],
                        default="PROMOTION",
                        max_length=30,
                    ),
                ),
                ("source_ref", models.CharField(blank=True, max_length=100)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_credits",
                        to="companyio.company",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="ReferralCode",
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
                ("code", models.CharField(db_index=True, max_length=50, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("total_redemptions", models.PositiveIntegerField(default=0)),
                (
                    "max_redemptions",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="referral_codes",
                        to="companyio.company",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="ReferralRedemption",
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
                    "referral_code",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="redemptions",
                        to="subscriptionio.referralcode",
                    ),
                ),
                (
                    "referred_company",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="referral_redemption",
                        to="companyio.company",
                    ),
                ),
                (
                    "reward_credit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="referral_redemptions",
                        to="subscriptionio.subscriptioncredit",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="CouponRedemption",
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
                    "checkout_session_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "discount_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coupon_redemptions",
                        to="companyio.company",
                    ),
                ),
                (
                    "coupon",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="redemptions",
                        to="subscriptionio.subscriptioncoupon",
                    ),
                ),
                (
                    "redeemed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="employeeio.employee",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="trial_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="trial_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="applied_coupon",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="company_subscriptions",
                to="subscriptionio.subscriptioncoupon",
            ),
        ),
    ]
