from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils.timezone import now

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import CompanySubscription, SubscriptionPrice, SubscriptionProgramSettings
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.plan_version_service import PlanVersionService
from subscriptionio.services.subscription_event_service import SubscriptionEventService


@dataclass
class TrialStatusResult:
    eligible: bool
    active: bool
    status: str | None
    trial_start: Any = None
    trial_end: Any = None
    days_remaining: int | None = None
    plan_title: str | None = None
    message: str = ""


class TrialService:
    NOT_ELIGIBLE_MESSAGE = "This company is not eligible for a trial."
    NO_TRIAL_PLAN_MESSAGE = "The selected plan does not include a trial period."
    ALREADY_USED_MESSAGE = "A trial has already been used for this company."
    DOMAIN_TRIAL_MESSAGE = "A trial has already been used for this email domain."
    CARD_REQUIRED_MESSAGE = "A payment method is required to start a trial."

    @classmethod
    def _email_domain(cls, company) -> str | None:
        email = (company.email or "").strip().lower()
        if "@" not in email:
            return None
        return email.rsplit("@", 1)[-1]

    @classmethod
    def _domain_has_prior_trial(cls, company) -> bool:
        domain = cls._email_domain(company)
        if not domain:
            return False
        return (
            CompanySubscription.objects.filter(
                kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
                trial_start__isnull=False,
                company__email__iendswith=f"@{domain}",
            )
            .exclude(company=company)
            .exists()
        )

    @classmethod
    def _effective_trial_days(cls, subscription, settings: SubscriptionProgramSettings) -> int:
        if subscription.trial_period and subscription.trial_period > 0:
            return subscription.trial_period
        return settings.trial_default_days or 0

    @classmethod
    def _has_prior_paid_subscription(cls, company) -> bool:
        return CompanySubscription.objects.filter(
            company=company,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            status__in=[
                CompanySubscriptionStatusChoices.ACTIVE,
                CompanySubscriptionStatusChoices.CANCELED,
                CompanySubscriptionStatusChoices.EXPIRED,
            ],
        ).exists()

    @classmethod
    def _has_prior_trial(cls, company) -> bool:
        return CompanySubscription.objects.filter(
            company=company,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            trial_start__isnull=False,
        ).exists()

    @classmethod
    def get_status(cls, company) -> TrialStatusResult:
        settings = SubscriptionProgramSettings.get_solo()
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            eligible = not cls._has_prior_trial(company)
            if eligible and settings.trial_one_per_domain and cls._domain_has_prior_trial(company):
                eligible = False
            return TrialStatusResult(
                eligible=eligible,
                active=False,
                status=None,
                message=(
                    cls.DOMAIN_TRIAL_MESSAGE
                    if settings.trial_one_per_domain and cls._domain_has_prior_trial(company)
                    else cls.NOT_ELIGIBLE_MESSAGE if cls._has_prior_trial(company) else ""
                ),
            )

        subscription = company_subscription.subscription_price.subscription
        trial_end = company_subscription.trial_end
        active = (
            company_subscription.status == CompanySubscriptionStatusChoices.TRIALING
            and trial_end
            and now() <= trial_end
        )
        days_remaining = None
        if active and trial_end:
            days_remaining = max(0, (trial_end - now()).days)

        return TrialStatusResult(
            eligible=False,
            active=active,
            status=company_subscription.status,
            trial_start=company_subscription.trial_start,
            trial_end=trial_end,
            days_remaining=days_remaining,
            plan_title=subscription.title,
        )

    @classmethod
    def _resolve_subscription_price(
        cls,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
    ) -> SubscriptionPrice | None:
        if subscription_price:
            return subscription_price
        if subscription_price_slug:
            return SubscriptionPrice.objects.filter(slug=subscription_price_slug).first()
        if plan_title and billing_frequency:
            return SubscriptionPrice.objects.filter(
                subscription__title=plan_title,
                billing_frequency=billing_frequency,
            ).first()
        return None

    @classmethod
    @transaction.atomic
    def start_trial(
        cls,
        company,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        created_by=None,
    ) -> TrialStatusResult:
        settings = SubscriptionProgramSettings.get_solo()

        if cls._has_prior_trial(company) or cls._has_prior_paid_subscription(company):
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message=cls.ALREADY_USED_MESSAGE,
            )

        if settings.trial_one_per_domain and cls._domain_has_prior_trial(company):
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message=cls.DOMAIN_TRIAL_MESSAGE,
            )

        subscription_price = cls._resolve_subscription_price(
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
        )
        if not subscription_price:
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message="Subscription price not found.",
            )

        subscription = subscription_price.subscription
        trial_days = cls._effective_trial_days(subscription, settings)
        if trial_days <= 0:
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message=cls.NO_TRIAL_PLAN_MESSAGE,
            )

        company_subscription = CompanySubscription.objects.filter(
            company=company,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
        ).first()
        if settings.trial_card_required and not getattr(
            company_subscription, "stripe_customer_id", None
        ):
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message=cls.CARD_REQUIRED_MESSAGE,
            )

        trial_start = now()
        trial_end = trial_start + timedelta(days=trial_days)

        plan_version = PlanVersionService.ensure_initial_version(subscription)

        if company_subscription:
            company_subscription.subscription_price = subscription_price
            company_subscription.status = CompanySubscriptionStatusChoices.TRIALING
            company_subscription.trial_start = trial_start
            company_subscription.trial_end = trial_end
            company_subscription.plan_version = plan_version
            company_subscription.save(
                update_fields=[
                    "subscription_price",
                    "status",
                    "trial_start",
                    "trial_end",
                    "plan_version",
                    "updated_at",
                ]
            )
        else:
            company_subscription = CompanySubscription.objects.create(
                company=company,
                subscription_price=subscription_price,
                status=CompanySubscriptionStatusChoices.TRIALING,
                kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
                trial_start=trial_start,
                trial_end=trial_end,
                plan_version=plan_version,
                created_by=created_by,
            )

        invalidate_entitlement_cache(company.id)
        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.TRIAL_STARTED,
            new_status=CompanySubscriptionStatusChoices.TRIALING,
            source=SubscriptionEventSourceChoices.API,
            actor=created_by,
            payload={
                "trial_end": trial_end.isoformat(),
                "plan_title": subscription.title,
            },
        )
        return cls.get_status(company)

    @classmethod
    @transaction.atomic
    def extend_trial(cls, company, extra_days: int) -> TrialStatusResult:
        settings = SubscriptionProgramSettings.get_solo()
        if extra_days <= 0:
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message="Extension days must be greater than zero.",
            )
        if extra_days > settings.trial_max_extension_days:
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message=(
                    f"Extension cannot exceed {settings.trial_max_extension_days} days."
                ),
            )

        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription or not company_subscription.trial_end:
            return TrialStatusResult(
                eligible=False,
                active=False,
                status=None,
                message="No active trial to extend.",
            )

        company_subscription.trial_end = company_subscription.trial_end + timedelta(
            days=extra_days
        )
        company_subscription.status = CompanySubscriptionStatusChoices.TRIALING
        company_subscription.save(update_fields=["trial_end", "status", "updated_at"])
        invalidate_entitlement_cache(company.id)
        return cls.get_status(company)

    @classmethod
    @transaction.atomic
    def convert_to_paid(cls, company_subscription: CompanySubscription):
        company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        company_subscription.trial_start = None
        company_subscription.trial_end = None
        company_subscription.save(
            update_fields=["status", "trial_start", "trial_end", "updated_at"]
        )
        invalidate_entitlement_cache(company_subscription.company_id)
        SubscriptionEventService.record(
            company=company_subscription.company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.TRIAL_CONVERTED,
            previous_status=CompanySubscriptionStatusChoices.TRIALING,
            new_status=CompanySubscriptionStatusChoices.ACTIVE,
            source=SubscriptionEventSourceChoices.WEBHOOK,
        )

    @classmethod
    def expire_due_trials(cls) -> int:
        expired_count = 0
        due_subscriptions = CompanySubscription.objects.filter(
            status=CompanySubscriptionStatusChoices.TRIALING,
            trial_end__lt=now(),
        )
        for company_subscription in due_subscriptions.iterator():
            previous_status = company_subscription.status
            company_subscription.status = CompanySubscriptionStatusChoices.EXPIRED
            company_subscription.save(update_fields=["status", "updated_at"])
            invalidate_entitlement_cache(company_subscription.company_id)
            SubscriptionEventService.record(
                company=company_subscription.company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.TRIAL_EXPIRED,
                previous_status=previous_status,
                new_status=company_subscription.status,
                source=SubscriptionEventSourceChoices.SYSTEM,
            )
            expired_count += 1
        return expired_count
