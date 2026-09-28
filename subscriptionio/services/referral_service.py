import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.timezone import now

from subscriptionio.choices import (
    ReferralRedemptionStatusChoices,
    SubscriptionCreditSourceChoices,
)
from subscriptionio.models import (
    ReferralCode,
    ReferralRedemption,
    SubscriptionCredit,
    SubscriptionProgramSettings,
)


@dataclass
class ReferralValidationResult:
    valid: bool
    referral_code: ReferralCode | None = None
    message: str = ""


class ReferralService:
    INVALID_MESSAGE = "This referral code is not valid."
    SELF_REFERRAL_MESSAGE = "You cannot use your own referral code."
    ALREADY_REFERRED_MESSAGE = "This company has already used a referral code."
    LIMIT_MESSAGE = "This referral code has reached its redemption limit."
    PROGRAM_INACTIVE_MESSAGE = "The referral program is not currently active."
    MONTHLY_LIMIT_MESSAGE = "This referrer has reached the monthly referral limit."
    DEFAULT_REWARD_AMOUNT = Decimal("25.00")

    @classmethod
    def _monthly_redemption_count(cls, referral: ReferralCode) -> int:
        start_of_month = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return ReferralRedemption.objects.filter(
            referral_code__company=referral.company,
            created_at__gte=start_of_month,
        ).exclude(status=ReferralRedemptionStatusChoices.REJECTED).count()

    @classmethod
    def _normalize_code(cls, code: str) -> str:
        return (code or "").strip().upper()

    @classmethod
    def get_or_create_company_code(cls, company) -> ReferralCode:
        existing = ReferralCode.objects.filter(company=company, is_active=True).first()
        if existing:
            return existing

        code = f"REF-{secrets.token_hex(4).upper()}"
        while ReferralCode.objects.filter(code=code).exists():
            code = f"REF-{secrets.token_hex(4).upper()}"

        return ReferralCode.objects.create(company=company, code=code)

    @classmethod
    def validate(cls, referral_code: str, *, company) -> ReferralValidationResult:
        settings = SubscriptionProgramSettings.get_solo()
        if not settings.referral_program_active:
            return ReferralValidationResult(
                valid=False,
                message=cls.PROGRAM_INACTIVE_MESSAGE,
            )

        code = cls._normalize_code(referral_code)
        if not code:
            return ReferralValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        referral = ReferralCode.objects.filter(code__iexact=code, is_active=True).first()
        if not referral:
            return ReferralValidationResult(valid=False, message=cls.INVALID_MESSAGE)

        if referral.company_id == company.id:
            return ReferralValidationResult(
                valid=False,
                referral_code=referral,
                message=cls.SELF_REFERRAL_MESSAGE,
            )

        if ReferralRedemption.objects.filter(referred_company=company).exists():
            return ReferralValidationResult(
                valid=False,
                referral_code=referral,
                message=cls.ALREADY_REFERRED_MESSAGE,
            )

        if (
            referral.max_redemptions is not None
            and referral.total_redemptions >= referral.max_redemptions
        ):
            return ReferralValidationResult(
                valid=False,
                referral_code=referral,
                message=cls.LIMIT_MESSAGE,
            )

        if settings.referral_max_per_month is not None:
            if cls._monthly_redemption_count(referral) >= settings.referral_max_per_month:
                return ReferralValidationResult(
                    valid=False,
                    referral_code=referral,
                    message=cls.MONTHLY_LIMIT_MESSAGE,
                )

        return ReferralValidationResult(valid=True, referral_code=referral)

    @classmethod
    def _reward_amount(cls) -> Decimal:
        settings = SubscriptionProgramSettings.get_solo()
        return settings.referral_reward_amount or cls.DEFAULT_REWARD_AMOUNT

    @classmethod
    @transaction.atomic
    def redeem(
        cls,
        referral: ReferralCode,
        *,
        referred_company,
        reward_amount: Decimal | None = None,
    ) -> ReferralRedemption:
        settings = SubscriptionProgramSettings.get_solo()
        if not settings.referral_program_active:
            raise ValueError(cls.PROGRAM_INACTIVE_MESSAGE)

        validation = cls.validate(referral.code, company=referred_company)
        if not validation.valid:
            raise ValueError(validation.message)

        reward_amount = reward_amount or cls._reward_amount()
        require_approval = settings.referral_require_approval

        if require_approval:
            redemption = ReferralRedemption.objects.create(
                referral_code=referral,
                referred_company=referred_company,
                status=ReferralRedemptionStatusChoices.PENDING,
            )
            return redemption

        referrer_credit = SubscriptionCredit.objects.create(
            company=referral.company,
            initial_amount=reward_amount,
            balance=reward_amount,
            source=SubscriptionCreditSourceChoices.REFERRAL,
            source_ref=referral.code,
        )
        redemption = ReferralRedemption.objects.create(
            referral_code=referral,
            referred_company=referred_company,
            status=ReferralRedemptionStatusChoices.APPROVED,
            reward_credit=referrer_credit,
        )
        referral.total_redemptions += 1
        referral.save(update_fields=["total_redemptions", "updated_at"])
        return redemption

    @classmethod
    def get_referral_dashboard(cls, company) -> dict[str, Any]:
        from django.db.models import Sum

        settings = SubscriptionProgramSettings.get_solo()
        referral = cls.get_or_create_company_code(company)
        redemptions = (
            ReferralRedemption.objects.filter(referral_code__company=company)
            .select_related("referred_company", "reward_credit")
            .order_by("-created_at")
        )
        credits = SubscriptionCredit.objects.filter(
            company=company,
            source=SubscriptionCreditSourceChoices.REFERRAL,
        ).order_by("-created_at")

        pending = redemptions.filter(status=ReferralRedemptionStatusChoices.PENDING)
        approved = redemptions.filter(status=ReferralRedemptionStatusChoices.APPROVED)
        total_earned = credits.aggregate(total=Sum("initial_amount"))["total"] or Decimal("0")
        available_credit = credits.filter(is_active=True).aggregate(
            total=Sum("balance")
        )["total"] or Decimal("0")

        return {
            "code": referral.code,
            "total_redemptions": referral.total_redemptions,
            "is_active": referral.is_active,
            "program_active": settings.referral_program_active,
            "reward_amount": str(cls._reward_amount()),
            "summary": {
                "pending_count": pending.count(),
                "approved_count": approved.count(),
                "rejected_count": redemptions.filter(
                    status=ReferralRedemptionStatusChoices.REJECTED
                ).count(),
                "total_earned": str(total_earned.quantize(Decimal("0.01"))),
                "available_credit": str(available_credit.quantize(Decimal("0.01"))),
            },
            "redemptions": [
                {
                    "uid": str(item.uid),
                    "status": item.status,
                    "referred_company_name": item.referred_company.name,
                    "referred_company_uid": str(item.referred_company.uid),
                    "reward_amount": str(
                        item.reward_credit.initial_amount
                        if item.reward_credit
                        else cls._reward_amount()
                    ),
                    "created_at": item.created_at,
                }
                for item in redemptions[:50]
            ],
            "credits": [
                {
                    "uid": str(item.uid),
                    "initial_amount": str(item.initial_amount),
                    "balance": str(item.balance),
                    "source": item.source,
                    "source_ref": item.source_ref,
                    "is_active": item.is_active,
                    "expires_at": item.expires_at,
                    "created_at": item.created_at,
                }
                for item in credits[:50]
            ],
        }
