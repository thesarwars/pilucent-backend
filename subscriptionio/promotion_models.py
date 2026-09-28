from django.db import models

from common.choices import DiscountKind
from common.models import BaseModelWithUID

from .choices import (
    CouponStatusChoices,
    OfferStatusChoices,
    ReferralRedemptionStatusChoices,
    SubscriptionCreditSourceChoices,
)


class SubscriptionCoupon(BaseModelWithUID):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=CouponStatusChoices,
        default=CouponStatusChoices.ACTIVE,
    )
    discount_kind = models.CharField(
        max_length=20,
        choices=DiscountKind,
        default=DiscountKind.PERCENTAGE,
    )
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)
    max_redemptions = models.PositiveIntegerField(blank=True, null=True)
    redemption_count = models.PositiveIntegerField(default=0)
    max_redemptions_per_company = models.PositiveIntegerField(default=1)
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_until = models.DateTimeField(blank=True, null=True)
    is_stackable = models.BooleanField(default=False)
    stripe_coupon_id = models.CharField(max_length=255, blank=True, null=True)
    notes = models.TextField(blank=True)
    applies_to_subscriptions = models.ManyToManyField(
        "subscriptionio.Subscription",
        blank=True,
        related_name="coupons",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.code


class CouponRedemption(BaseModelWithUID):
    coupon = models.ForeignKey(
        SubscriptionCoupon,
        on_delete=models.CASCADE,
        related_name="redemptions",
    )
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="coupon_redemptions",
    )
    redeemed_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    checkout_session_id = models.CharField(max_length=255, blank=True, null=True)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.coupon.code} -> {self.company_id}"


class SubscriptionOffer(BaseModelWithUID):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=OfferStatusChoices,
        default=OfferStatusChoices.DRAFT,
    )
    coupon = models.ForeignKey(
        SubscriptionCoupon,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="offers",
    )
    is_retention_offer = models.BooleanField(default=False)
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_until = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.code


class ReferralCode(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="referral_codes",
    )
    code = models.CharField(max_length=50, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    total_redemptions = models.PositiveIntegerField(default=0)
    max_redemptions = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.code


class ReferralRedemption(BaseModelWithUID):
    referral_code = models.ForeignKey(
        ReferralCode,
        on_delete=models.CASCADE,
        related_name="redemptions",
    )
    referred_company = models.OneToOneField(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="referral_redemption",
    )
    status = models.CharField(
        max_length=20,
        choices=ReferralRedemptionStatusChoices,
        default=ReferralRedemptionStatusChoices.APPROVED,
        db_index=True,
    )
    reward_credit = models.ForeignKey(
        "subscriptionio.SubscriptionCredit",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="referral_redemptions",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.referral_code.code} -> {self.referred_company_id}"


class SubscriptionProgramSettings(BaseModelWithUID):
    referral_reward_amount = models.DecimalField(max_digits=12, decimal_places=2, default=25)
    referral_max_per_month = models.PositiveIntegerField(blank=True, null=True)
    referral_require_approval = models.BooleanField(default=False)
    referral_program_active = models.BooleanField(default=True)
    trial_default_days = models.PositiveIntegerField(default=14)
    trial_card_required = models.BooleanField(default=False)
    trial_auto_convert = models.BooleanField(default=True)
    trial_reminder_days = models.JSONField(default=list)
    trial_max_extension_days = models.PositiveIntegerField(default=7)
    trial_one_per_domain = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Subscription program settings"

    def __str__(self):
        return "Subscription program settings"

    @classmethod
    def get_solo(cls):
        settings, _ = cls.objects.get_or_create(
            defaults={
                "trial_reminder_days": [7, 3, 1],
            }
        )
        if not settings.trial_reminder_days:
            settings.trial_reminder_days = [7, 3, 1]
            settings.save(update_fields=["trial_reminder_days", "updated_at"])
        return settings


class SubscriptionCredit(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="subscription_credits",
    )
    initial_amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(
        max_length=30,
        choices=SubscriptionCreditSourceChoices,
        default=SubscriptionCreditSourceChoices.PROMOTION,
    )
    source_ref = models.CharField(max_length=100, blank=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.company_id} credit={self.balance}"
