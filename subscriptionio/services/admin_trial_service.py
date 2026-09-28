from typing import Any

from django.db.models import Q
from django.utils.timezone import now

from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import CompanySubscription, SubscriptionProgramSettings
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.subscription_event_service import SubscriptionEventService
from subscriptionio.services.trial_service import TrialService


class AdminTrialService:
    @classmethod
    def _serialize_settings(cls, settings: SubscriptionProgramSettings) -> dict[str, Any]:
        return {
            "trial_default_days": settings.trial_default_days,
            "trial_card_required": settings.trial_card_required,
            "trial_auto_convert": settings.trial_auto_convert,
            "trial_reminder_days": settings.trial_reminder_days or [7, 3, 1],
            "trial_max_extension_days": settings.trial_max_extension_days,
            "trial_one_per_domain": settings.trial_one_per_domain,
        }

    @classmethod
    def get_settings(cls) -> dict[str, Any]:
        return cls._serialize_settings(SubscriptionProgramSettings.get_solo())

    @classmethod
    def update_settings(cls, payload: dict[str, Any]) -> dict[str, Any]:
        settings = SubscriptionProgramSettings.get_solo()
        field_map = {
            "trial_default_days": "trial_default_days",
            "trial_card_required": "trial_card_required",
            "trial_auto_convert": "trial_auto_convert",
            "trial_reminder_days": "trial_reminder_days",
            "trial_max_extension_days": "trial_max_extension_days",
            "trial_one_per_domain": "trial_one_per_domain",
        }
        update_fields = ["updated_at"]
        for key, field in field_map.items():
            if key not in payload:
                continue
            setattr(settings, field, payload[key])
            update_fields.append(field)
        settings.save(update_fields=update_fields)
        return cls._serialize_settings(settings)

    @classmethod
    def _serialize_trial_row(cls, company_subscription: CompanySubscription) -> dict[str, Any]:
        company = company_subscription.company
        subscription_price = company_subscription.subscription_price
        subscription = subscription_price.subscription
        trial_end = company_subscription.trial_end
        days_remaining = None
        if trial_end:
            days_remaining = max(0, (trial_end - now()).days)

        has_payment_method = bool(company_subscription.stripe_customer_id)

        return {
            "company_uid": str(company.uid),
            "company_name": company.name,
            "company_email": company.email,
            "plan_uid": str(subscription.uid),
            "plan_title": subscription.title,
            "status": company_subscription.status,
            "trial_start": company_subscription.trial_start,
            "trial_end": trial_end,
            "days_remaining": days_remaining,
            "has_payment_method": has_payment_method,
            "billing_frequency": subscription_price.billing_frequency,
        }

    @classmethod
    def get_active_trials_queryset(cls, *, search: str | None = None):
        queryset = CompanySubscription.objects.filter(
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            status=CompanySubscriptionStatusChoices.TRIALING,
            trial_end__gte=now(),
        ).select_related(
            "company",
            "subscription_price__subscription",
        ).order_by("trial_end")

        if search:
            queryset = queryset.filter(
                Q(company__name__icontains=search)
                | Q(company__email__icontains=search)
            )
        return queryset

    @classmethod
    def serialize_trial_rows(cls, company_subscriptions) -> list[dict[str, Any]]:
        return [cls._serialize_trial_row(item) for item in company_subscriptions]

    @classmethod
    def list_active_trials(cls, *, search: str | None = None) -> dict[str, Any]:
        trials = cls.serialize_trial_rows(cls.get_active_trials_queryset(search=search))
        return {
            "count": len(trials),
            "results": trials,
        }

    @classmethod
    def extend_trial(cls, company, *, days: int, actor=None) -> dict[str, Any]:
        settings = SubscriptionProgramSettings.get_solo()
        if days > settings.trial_max_extension_days:
            raise ValueError(
                f"Extension cannot exceed {settings.trial_max_extension_days} days."
            )

        result = TrialService.extend_trial(company, extra_days=days)
        if not result.active and result.message:
            raise ValueError(result.message)

        company_subscription = EntitlementService.get_company_subscription(company)
        if company_subscription:
            SubscriptionEventService.record(
                company=company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.TRIAL_STARTED,
                previous_status=CompanySubscriptionStatusChoices.TRIALING,
                new_status=CompanySubscriptionStatusChoices.TRIALING,
                source=SubscriptionEventSourceChoices.ADMIN,
                actor=actor,
                payload={
                    "action": "extend_trial",
                    "extra_days": days,
                    "trial_end": result.trial_end.isoformat() if result.trial_end else None,
                },
            )

        return {
            "trial_end": result.trial_end,
            "days_remaining": result.days_remaining,
            "status": result.status,
        }

    @classmethod
    def convert_trial(cls, company, *, actor=None) -> dict[str, Any]:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            raise ValueError("No subscription found for this company.")
        if company_subscription.status != CompanySubscriptionStatusChoices.TRIALING:
            raise ValueError("Company is not on an active trial.")

        previous_status = company_subscription.status
        TrialService.convert_to_paid(company_subscription)

        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.TRIAL_CONVERTED,
            previous_status=previous_status,
            new_status=CompanySubscriptionStatusChoices.ACTIVE,
            source=SubscriptionEventSourceChoices.ADMIN,
            actor=actor,
            payload={"action": "admin_convert_trial"},
        )

        company_subscription.refresh_from_db()
        return {
            "company_uid": str(company.uid),
            "status": company_subscription.status,
            "trial_start": company_subscription.trial_start,
            "trial_end": company_subscription.trial_end,
        }
