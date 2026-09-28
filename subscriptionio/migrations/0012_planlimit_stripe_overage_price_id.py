from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptionio", "0011_billing_mvp_phase2"),
    ]

    operations = [
        migrations.AddField(
            model_name="planlimit",
            name="stripe_overage_price_id",
            field=models.CharField(
                blank=True,
                help_text="Optional Stripe price ID for recurring overage seats.",
                max_length=255,
                null=True,
            ),
        ),
    ]
