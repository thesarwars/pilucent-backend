from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now

from subscriptionio.choices import (
    ReferralRedemptionStatusChoices,
    SubscriptionCreditSourceChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import (
    ReferralCode,
    ReferralRedemption,
    SubscriptionCredit,
    SubscriptionProgramSettings,
)
from subscriptionio.services.referral_service import ReferralService
from subscriptionio.services.subscription_event_service import SubscriptionEventService


class AdminReferralService:
    @classmethod
    def _serialize_settings(cls, settings: SubscriptionProgramSettings) -> dict[str, Any]:
        return {
            "referral_reward_amount": str(settings.referral_reward_amount),
            "referral_max_per_month": settings.referral_max_per_month,
            "referral_require_approval": settings.referral_require_approval,
            "referral_program_active": settings.referral_program_active,
        }

    @classmethod
    def get_settings(cls) -> dict[str, Any]:
        return cls._serialize_settings(SubscriptionProgramSettings.get_solo())

    @classmethod
    def update_settings(cls, payload: dict[str, Any]) -> dict[str, Any]:
        settings = SubscriptionProgramSettings.get_solo()
        field_map = {
            "referral_reward_amount": "referral_reward_amount",
            "referral_max_per_month": "referral_max_per_month",
            "referral_require_approval": "referral_require_approval",
            "referral_program_active": "referral_program_active",
        }
        update_fields = ["updated_at"]
        for key, field in field_map.items():
            if key not in payload:
                continue
            value = payload[key]
            if field == "referral_reward_amount":
                value = Decimal(str(value))
            setattr(settings, field, value)
            update_fields.append(field)
        settings.save(update_fields=update_fields)
        return cls._serialize_settings(settings)

    @classmethod
    def _serialize_redemption(cls, redemption: ReferralRedemption) -> dict[str, Any]:
        referrer = redemption.referral_code.company
        referred = redemption.referred_company
        reward_amount = None
        if redemption.reward_credit:
            reward_amount = str(redemption.reward_credit.initial_amount)
        else:
            reward_amount = str(ReferralService._reward_amount())

        return {
            "uid": str(redemption.uid),
            "status": redemption.status,
            "referral_code": redemption.referral_code.code,
            "referrer_company_uid": str(referrer.uid),
            "referrer_company_name": referrer.name,
            "referrer_company_email": referrer.email,
            "referred_company_uid": str(referred.uid),
            "referred_company_name": referred.name,
            "referred_company_email": referred.email,
            "reward_amount": reward_amount,
            "created_at": redemption.created_at,
        }

    @classmethod
    def get_summary(cls) -> dict[str, Any]:
        redemptions = ReferralRedemption.objects.all()
        pending_total = redemptions.filter(
            status=ReferralRedemptionStatusChoices.PENDING
        ).count()
        approved = redemptions.filter(status=ReferralRedemptionStatusChoices.APPROVED)
        paid_total = (
            approved.aggregate(total=Sum("reward_credit__initial_amount"))["total"]
            or Decimal("0")
        )
        pending_amount = Decimal(pending_total) * ReferralService._reward_amount()
        return {
            "total_referred": redemptions.count(),
            "pending_count": pending_total,
            "pending_amount": str(pending_amount.quantize(Decimal("0.01"))),
            "paid_amount": str(paid_total.quantize(Decimal("0.01"))),
            "active_codes": ReferralCode.objects.filter(is_active=True).count(),
        }

    @classmethod
    def get_activity_queryset(
        cls,
        *,
        status: str | None = None,
        search: str | None = None,
    ):
        queryset = ReferralRedemption.objects.select_related(
            "referral_code__company",
            "referred_company",
            "reward_credit",
        ).order_by("-created_at")

        if status:
            queryset = queryset.filter(status=status)

        if search:
            queryset = queryset.filter(
                Q(referral_code__code__icontains=search)
                | Q(referral_code__company__name__icontains=search)
                | Q(referral_code__company__email__icontains=search)
                | Q(referred_company__name__icontains=search)
                | Q(referred_company__email__icontains=search)
            )
        return queryset

    @classmethod
    def serialize_redemptions(cls, redemptions) -> list[dict[str, Any]]:
        return [cls._serialize_redemption(item) for item in redemptions]

    @classmethod
    def list_activity(
        cls,
        *,
        status: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        queryset = cls.get_activity_queryset(status=status, search=search)
        return {
            "summary": cls.get_summary(),
            "results": cls.serialize_redemptions(queryset[:200]),
        }

    @classmethod
    @transaction.atomic
    def approve(cls, redemption: ReferralRedemption, *, actor=None) -> dict[str, Any]:
        if redemption.status != ReferralRedemptionStatusChoices.PENDING:
            raise ValueError("Only pending referrals can be approved.")

        reward_amount = ReferralService._reward_amount()
        referrer_credit = SubscriptionCredit.objects.create(
            company=redemption.referral_code.company,
            initial_amount=reward_amount,
            balance=reward_amount,
            source=SubscriptionCreditSourceChoices.REFERRAL,
            source_ref=redemption.referral_code.code,
        )
        redemption.status = ReferralRedemptionStatusChoices.APPROVED
        redemption.reward_credit = referrer_credit
        redemption.save(update_fields=["status", "reward_credit", "updated_at"])

        referral = redemption.referral_code
        referral.total_redemptions += 1
        referral.save(update_fields=["total_redemptions", "updated_at"])

        SubscriptionEventService.record(
            company=redemption.referral_code.company,
            event_type=SubscriptionEventTypeChoices.REFERRAL_APPROVED,
            source=SubscriptionEventSourceChoices.ADMIN,
            actor=actor,
            payload={
                "redemption_uid": str(redemption.uid),
                "referred_company_uid": str(redemption.referred_company.uid),
                "reward_amount": str(reward_amount),
            },
        )
        return cls._serialize_redemption(redemption)

    @classmethod
    @transaction.atomic
    def reject(cls, redemption: ReferralRedemption, *, actor=None, reason: str = "") -> dict[str, Any]:
        if redemption.status != ReferralRedemptionStatusChoices.PENDING:
            raise ValueError("Only pending referrals can be rejected.")

        redemption.status = ReferralRedemptionStatusChoices.REJECTED
        redemption.save(update_fields=["status", "updated_at"])

        SubscriptionEventService.record(
            company=redemption.referral_code.company,
            event_type=SubscriptionEventTypeChoices.REFERRAL_REJECTED,
            source=SubscriptionEventSourceChoices.ADMIN,
            actor=actor,
            payload={
                "redemption_uid": str(redemption.uid),
                "referred_company_uid": str(redemption.referred_company.uid),
                "reason": reason,
            },
        )
        return cls._serialize_redemption(redemption)
