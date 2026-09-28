from dataclasses import dataclass, field
from typing import Any

from dateutil.relativedelta import relativedelta

from django.utils.timezone import now

from paymentio.choices import PaymentInformationKindChoices

from subscriptionio.cache import (
    get_cached_entitlements,
    invalidate_entitlement_cache,
    set_cached_entitlements,
)
from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    LimitMetricChoices,
    PlanVersionStatusChoices,
    SubscriptionKindChoices,
    SubscriptionStatusChoices,
)
from subscriptionio.feature_catalog import LEGACY_FEATURE_FIELDS
from subscriptionio.models import CompanySubscription, PlanVersion, SubscriptionFeature
from subscriptionio.services.enterprise_pricing_service import EnterprisePricingService

from common.django_rest.helpers.payment_helpers import get_subscription_period


OPERATIONAL_STATUSES = {
    CompanySubscriptionStatusChoices.ACTIVE,
    CompanySubscriptionStatusChoices.TRIALING,
    CompanySubscriptionStatusChoices.GRACE,
}

BILLING_ONLY_STATUSES = {
    CompanySubscriptionStatusChoices.PAST_DUE,
    CompanySubscriptionStatusChoices.SUSPENDED,
    CompanySubscriptionStatusChoices.CANCELED,
    CompanySubscriptionStatusChoices.EXPIRED,
}


@dataclass
class EntitlementResult:
    allowed: bool
    feature_code: str | None = None
    legacy_field: str | None = None
    denied_by: str | None = None
    message: str = ""
    upgrade_metadata: dict[str, Any] = field(default_factory=dict)


class EntitlementService:
    INACTIVE_MESSAGE = (
        "Access denied! It seems like your subscription is inactive. "
        "Please activate your subscription to unlock this feature."
    )
    FEATURE_DENIED_MESSAGE = (
        "This feature is not included in your current plan. "
        "Please upgrade your subscription to unlock it."
    )
    EXPIRED_MESSAGE = (
        "Your subscription period has ended. Please renew to continue using this feature."
    )
    BILLING_ONLY_MESSAGE = (
        "Your account has restricted access. Please update billing to restore full access."
    )

    @classmethod
    def get_company_subscription(cls, company):
        if not company:
            return None
        return (
            CompanySubscription.objects.filter(
                company=company,
                kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            )
            .select_related(
                "subscription_price__subscription",
                "plan_version",
            )
            .first()
        )

    @classmethod
    def resolve_feature_identifier(cls, feature_identifier: str):
        if not feature_identifier:
            return None

        feature = SubscriptionFeature.objects.filter(
            code=feature_identifier, is_active=True
        ).first()
        if feature:
            return feature

        if feature_identifier.startswith("is_"):
            feature = SubscriptionFeature.objects.filter(
                legacy_field=feature_identifier, is_active=True
            ).first()
            if feature:
                return feature
            if feature_identifier == "is_banking":
                return SubscriptionFeature.objects.filter(
                    legacy_field="is_bank_transaction", is_active=True
                ).first()
            return None

        legacy_field = f"is_{feature_identifier}"
        return SubscriptionFeature.objects.filter(
            legacy_field=legacy_field, is_active=True
        ).first()

    @classmethod
    def _subscription_period_expired(cls, company_subscription):
        period_end = company_subscription.current_period_end
        if period_end:
            return now() > period_end

        renew_date = company_subscription.renew_date
        if renew_date:
            if getattr(renew_date, "tzinfo", None) is None:
                return now().date() > renew_date.date()
            return now() > renew_date

        period_months = get_subscription_period(
            company_subscription.subscription_price.billing_frequency
        )
        if not period_months:
            return False
        return now() > company_subscription.start_date + relativedelta(
            months=period_months
        )

    @classmethod
    def _mark_subscription_pending(cls, company_subscription):
        company_subscription.status = CompanySubscriptionStatusChoices.PENDING
        company_subscription.save(update_fields=["status", "updated_at"])
        company_subscription.subscription_price.subscription.paymentinformation_set.filter(
            is_subscription_completed=False,
            kind=PaymentInformationKindChoices.COMPANY_SUBSCRIPTION,
        ).update(is_subscription_completed=True)
        invalidate_entitlement_cache(company_subscription.company_id)

    @classmethod
    def _ensure_plan_version(cls, company_subscription):
        if company_subscription.plan_version_id:
            return company_subscription.plan_version

        subscription = company_subscription.subscription_price.subscription
        plan_version = (
            PlanVersion.objects.filter(
                subscription=subscription,
                status=PlanVersionStatusChoices.PUBLISHED,
            )
            .order_by("-version_no")
            .first()
        )
        if plan_version:
            company_subscription.plan_version = plan_version
            company_subscription.save(update_fields=["plan_version", "updated_at"])
        return plan_version

    @classmethod
    def _legacy_feature_enabled(cls, subscription, legacy_field: str) -> bool:
        if not subscription or not legacy_field:
            return False
        if subscription.status != SubscriptionStatusChoices.PUBLISHED:
            return False
        if legacy_field == "is_banking":
            legacy_field = "is_bank_transaction"
        return bool(getattr(subscription, legacy_field, False))

    @classmethod
    def _plan_feature_enabled(cls, plan_version, feature) -> bool:
        if not plan_version or not feature:
            return False
        plan_feature = plan_version.plan_features.filter(feature=feature).first()
        if plan_feature:
            return plan_feature.is_enabled
        return False

    @classmethod
    def is_feature_enabled(cls, company_subscription, feature_identifier: str) -> bool:
        feature = cls.resolve_feature_identifier(feature_identifier)
        subscription = company_subscription.subscription_price.subscription
        legacy_field = (
            feature.legacy_field
            if feature
            else (
                feature_identifier
                if feature_identifier and feature_identifier.startswith("is_")
                else None
            )
        )

        plan_version = cls._ensure_plan_version(company_subscription)
        if plan_version and feature:
            plan_feature = plan_version.plan_features.filter(feature=feature).first()
            if plan_feature is not None:
                return plan_feature.is_enabled

        if legacy_field:
            return cls._legacy_feature_enabled(subscription, legacy_field)

        if feature_identifier and feature_identifier.startswith("is_"):
            return cls._legacy_feature_enabled(subscription, feature_identifier)

        return False

    @classmethod
    def check_feature(cls, company, feature_identifier: str) -> EntitlementResult:
        company_subscription = cls.get_company_subscription(company)
        feature = cls.resolve_feature_identifier(feature_identifier)
        feature_code = feature.code if feature else feature_identifier
        legacy_field = (
            feature.legacy_field
            if feature
            else (
                feature_identifier
                if feature_identifier and feature_identifier.startswith("is_")
                else None
            )
        )

        if not company_subscription:
            return EntitlementResult(
                allowed=False,
                feature_code=feature_code,
                legacy_field=legacy_field,
                denied_by="subscription",
                message=cls.INACTIVE_MESSAGE,
            )

        status = company_subscription.status
        if status in BILLING_ONLY_STATUSES:
            return EntitlementResult(
                allowed=False,
                feature_code=feature_code,
                legacy_field=legacy_field,
                denied_by="subscription",
                message=cls.BILLING_ONLY_MESSAGE,
                upgrade_metadata={"subscription_status": status},
            )

        if status == CompanySubscriptionStatusChoices.TRIALING:
            trial_end = company_subscription.trial_end
            if trial_end and now() > trial_end:
                company_subscription.status = CompanySubscriptionStatusChoices.EXPIRED
                company_subscription.save(update_fields=["status", "updated_at"])
                invalidate_entitlement_cache(company.id)
                return EntitlementResult(
                    allowed=False,
                    feature_code=feature_code,
                    legacy_field=legacy_field,
                    denied_by="subscription",
                    message=cls.EXPIRED_MESSAGE,
                    upgrade_metadata={"subscription_status": "EXPIRED"},
                )

        if status not in OPERATIONAL_STATUSES:
            return EntitlementResult(
                allowed=False,
                feature_code=feature_code,
                legacy_field=legacy_field,
                denied_by="subscription",
                message=cls.INACTIVE_MESSAGE,
                upgrade_metadata={"subscription_status": status},
            )

        if cls._subscription_period_expired(company_subscription):
            cls._mark_subscription_pending(company_subscription)
            return EntitlementResult(
                allowed=False,
                feature_code=feature_code,
                legacy_field=legacy_field,
                denied_by="subscription",
                message=cls.EXPIRED_MESSAGE,
            )

        if cls.is_feature_enabled(company_subscription, feature_identifier):
            return EntitlementResult(
                allowed=True,
                feature_code=feature_code,
                legacy_field=legacy_field,
            )

        plan = company_subscription.subscription_price.subscription
        return EntitlementResult(
            allowed=False,
            feature_code=feature_code,
            legacy_field=legacy_field,
            denied_by="subscription",
            message=cls.FEATURE_DENIED_MESSAGE,
            upgrade_metadata={
                "feature": feature_code,
                "current_plan": plan.title,
                "suggested_action": "upgrade",
            },
        )

    @classmethod
    def _build_limits(cls, company_subscription) -> dict[str, Any]:
        plan_version = cls._ensure_plan_version(company_subscription)
        subscription = company_subscription.subscription_price.subscription
        limits: dict[str, Any] = {
            LimitMetricChoices.USER: subscription.user_limit,
            LimitMetricChoices.STORAGE: subscription.storage_limit,
        }

        contract = EnterprisePricingService.get_active_contract(
            company_subscription.company
        )
        if contract and contract.plan_version_id:
            plan_version = contract.plan_version

        if plan_version:
            for plan_limit in plan_version.limits.all():
                limits[plan_limit.metric_code] = {
                    "included_quantity": plan_limit.included_quantity,
                    "min_quantity": plan_limit.min_quantity,
                    "max_quantity": plan_limit.max_quantity,
                    "overage_unit_price": str(plan_limit.overage_unit_price),
                    "enforcement_mode": plan_limit.enforcement_mode,
                }

        if contract:
            if contract.employee_limit_override is not None:
                limits[LimitMetricChoices.EMPLOYEE] = {
                    **limits.get(LimitMetricChoices.EMPLOYEE, {}),
                    "included_quantity": contract.employee_limit_override,
                }
            if contract.user_limit_override is not None:
                limits[LimitMetricChoices.USER] = {
                    **limits.get(LimitMetricChoices.USER, {}),
                    "included_quantity": contract.user_limit_override,
                }
        return limits

    @classmethod
    def _build_features(cls, company_subscription) -> dict[str, bool]:
        features: dict[str, bool] = {}
        for legacy_field in LEGACY_FEATURE_FIELDS:
            features[legacy_field] = cls.is_feature_enabled(
                company_subscription, legacy_field
            )

        feature_catalog = SubscriptionFeature.objects.filter(is_active=True)
        for catalog_feature in feature_catalog:
            features[catalog_feature.code] = cls.is_feature_enabled(
                company_subscription, catalog_feature.code
            )
        return features

    @classmethod
    def get_entitlements(cls, company, use_cache: bool = True) -> dict[str, Any]:
        if not company:
            return {"features": {}, "limits": {}, "subscription_status": None}

        if use_cache:
            cached = get_cached_entitlements(company.id)
            if cached is not None:
                return cached

        company_subscription = cls.get_company_subscription(company)
        if not company_subscription:
            payload = {
                "features": {},
                "limits": {},
                "subscription_status": None,
                "plan_title": None,
                "plan_version": None,
            }
            return payload

        subscription = company_subscription.subscription_price.subscription
        plan_version = cls._ensure_plan_version(company_subscription)
        payload = {
            "features": cls._build_features(company_subscription),
            "limits": cls._build_limits(company_subscription),
            "subscription_status": company_subscription.status,
            "plan_title": subscription.title,
            "plan_version": plan_version.version_no if plan_version else None,
            "trial_period_days": subscription.trial_period,
        }
        set_cached_entitlements(company.id, payload)
        return payload

    @classmethod
    def get_limits(cls, company) -> dict[str, Any]:
        return cls.get_entitlements(company).get("limits", {})

    @classmethod
    def invalidate(cls, company_id):
        invalidate_entitlement_cache(company_id)
