# Generated manually for Phase 2 billing MVP

import dirtyfields.dirtyfields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptionio", "0010_entitlement_engine_phase1"),
        ("companyio", "__first__"),
        ("paymentio", "__first__"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="employee_limit",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="current_period_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companysubscription",
            name="current_period_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="SubscriptionInvoice",
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
                            ("DRAFT", "Draft"),
                            ("OPEN", "Open"),
                            ("PAID", "Paid"),
                            ("FAILED", "Failed"),
                            ("VOID", "Void"),
                        ],
                        db_index=True,
                        default="DRAFT",
                        max_length=20,
                    ),
                ),
                (
                    "currency",
                    models.CharField(default="USD", max_length=20),
                ),
                (
                    "subtotal",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                (
                    "discount_total",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                (
                    "tax_total",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                (
                    "total",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                ("period_start", models.DateTimeField(blank=True, null=True)),
                ("period_end", models.DateTimeField(blank=True, null=True)),
                (
                    "stripe_invoice_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=255,
                        null=True,
                        unique=True,
                    ),
                ),
                ("hosted_invoice_url", models.URLField(blank=True, null=True)),
                ("billing_reason", models.CharField(blank=True, max_length=50, null=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_invoices",
                        to="companyio.company",
                    ),
                ),
                (
                    "company_subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invoices",
                        to="subscriptionio.companysubscription",
                    ),
                ),
                (
                    "payment_information",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subscription_invoices",
                        to="paymentio.paymentinformation",
                    ),
                ),
                (
                    "subscription_price",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="subscriptionio.subscriptionprice",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name="SubscriptionInvoiceLine",
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
                    "line_type",
                    models.CharField(
                        choices=[
                            ("BASE", "Base Plan"),
                            ("OVERAGE", "Overage"),
                            ("DISCOUNT", "Discount"),
                            ("CREDIT", "Credit"),
                            ("TAX", "Tax"),
                        ],
                        default="BASE",
                        max_length=20,
                    ),
                ),
                ("description", models.CharField(max_length=255)),
                (
                    "quantity",
                    models.DecimalField(decimal_places=3, default=1, max_digits=19),
                ),
                (
                    "unit_amount",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                (
                    "amount",
                    models.DecimalField(decimal_places=3, default=0, max_digits=19),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="subscriptionio.subscriptioninvoice",
                    ),
                ),
            ],
            options={
                "ordering": ("id",),
            },
            bases=(dirtyfields.dirtyfields.DirtyFieldsMixin, models.Model),
        ),
    ]
