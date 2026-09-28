from django.db import transaction
from django.utils.timezone import now

from subscriptionio.choices import (
    FeatureAccessLevelChoices,
    LimitEnforcementModeChoices,
    LimitMetricChoices,
    PlanVersionStatusChoices,
)
from subscriptionio.feature_catalog import LEGACY_FEATURE_FIELDS
from subscriptionio.models import (
    PlanFeature,
    PlanLimit,
    PlanVersion,
    Subscription,
    SubscriptionFeature,
)


class PlanVersionService:
    @classmethod
    def get_next_version_no(cls, subscription: Subscription) -> int:
        latest = (
            PlanVersion.objects.filter(subscription=subscription)
            .order_by("-version_no")
            .first()
        )
        return (latest.version_no + 1) if latest else 1

    @classmethod
    def _sync_features_from_subscription(cls, plan_version: PlanVersion, subscription):
        for legacy_field in LEGACY_FEATURE_FIELDS:
            feature = SubscriptionFeature.objects.filter(
                legacy_field=legacy_field
            ).first()
            if not feature:
                continue
            PlanFeature.objects.update_or_create(
                plan_version=plan_version,
                feature=feature,
                defaults={
                    "is_enabled": bool(getattr(subscription, legacy_field, False)),
                    "access_level": FeatureAccessLevelChoices.FULL,
                },
            )

    @classmethod
    def _sync_limits_from_subscription(cls, plan_version: PlanVersion, subscription):
        PlanLimit.objects.update_or_create(
            plan_version=plan_version,
            metric_code=LimitMetricChoices.EMPLOYEE,
            defaults={
                "included_quantity": subscription.employee_limit,
                "overage_unit_price": 6,
                "enforcement_mode": LimitEnforcementModeChoices.AUTO_OVERAGE,
            },
        )
        PlanLimit.objects.update_or_create(
            plan_version=plan_version,
            metric_code=LimitMetricChoices.USER,
            defaults={
                "included_quantity": subscription.user_limit,
                "enforcement_mode": LimitEnforcementModeChoices.SOFT_WARNING,
            },
        )
        PlanLimit.objects.update_or_create(
            plan_version=plan_version,
            metric_code=LimitMetricChoices.STORAGE,
            defaults={
                "included_quantity": subscription.storage_limit,
                "enforcement_mode": LimitEnforcementModeChoices.SOFT_WARNING,
            },
        )

    @classmethod
    @transaction.atomic
    def create_draft_version(cls, subscription: Subscription) -> PlanVersion:
        version_no = cls.get_next_version_no(subscription)
        plan_version = PlanVersion.objects.create(
            subscription=subscription,
            version_no=version_no,
            status=PlanVersionStatusChoices.DRAFT,
            title=f"{subscription.title} v{version_no}",
        )
        cls._sync_features_from_subscription(plan_version, subscription)
        cls._sync_limits_from_subscription(plan_version, subscription)
        return plan_version

    @classmethod
    @transaction.atomic
    def publish(cls, plan_version: PlanVersion) -> PlanVersion:
        subscription = plan_version.subscription
        cls._sync_features_from_subscription(plan_version, subscription)
        cls._sync_limits_from_subscription(plan_version, subscription)

        PlanVersion.objects.filter(
            subscription=subscription,
            status=PlanVersionStatusChoices.PUBLISHED,
        ).exclude(id=plan_version.id).update(
            status=PlanVersionStatusChoices.ARCHIVED,
            effective_to=now(),
        )

        plan_version.publish()
        return plan_version

    @classmethod
    @transaction.atomic
    def clone(cls, source_version: PlanVersion) -> PlanVersion:
        subscription = source_version.subscription
        version_no = cls.get_next_version_no(subscription)
        new_version = PlanVersion.objects.create(
            subscription=subscription,
            version_no=version_no,
            status=PlanVersionStatusChoices.DRAFT,
            title=f"{subscription.title} v{version_no}",
            notes=f"Cloned from v{source_version.version_no}",
        )

        for plan_feature in source_version.plan_features.select_related("feature"):
            PlanFeature.objects.create(
                plan_version=new_version,
                feature=plan_feature.feature,
                is_enabled=plan_feature.is_enabled,
                access_level=plan_feature.access_level,
                limit_value=plan_feature.limit_value,
                metadata=plan_feature.metadata,
            )

        for plan_limit in source_version.limits.all():
            PlanLimit.objects.create(
                plan_version=new_version,
                metric_code=plan_limit.metric_code,
                included_quantity=plan_limit.included_quantity,
                min_quantity=plan_limit.min_quantity,
                max_quantity=plan_limit.max_quantity,
                overage_unit_price=plan_limit.overage_unit_price,
                enforcement_mode=plan_limit.enforcement_mode,
            )

        from subscriptionio.addon_models import PlanAddOn

        for plan_addon in source_version.plan_addons.select_related("add_on"):
            PlanAddOn.objects.create(
                plan_version=new_version,
                add_on=plan_addon.add_on,
                availability=plan_addon.availability,
            )

        return new_version

    @classmethod
    def ensure_initial_version(cls, subscription: Subscription) -> PlanVersion:
        existing = PlanVersion.objects.filter(subscription=subscription).first()
        if existing:
            return existing

        plan_version = cls.create_draft_version(subscription)
        return cls.publish(plan_version)

    @classmethod
    @transaction.atomic
    def update_draft_version(
        cls,
        plan_version: PlanVersion,
        *,
        plan_features: list[dict] | None = None,
        limits: list[dict] | None = None,
        notes: str | None = None,
    ) -> PlanVersion:
        if plan_version.status != PlanVersionStatusChoices.DRAFT:
            raise ValueError("Only draft plan versions can be edited.")

        if notes is not None:
            plan_version.notes = notes
            plan_version.save(update_fields=["notes", "updated_at"])

        if plan_features is not None:
            for item in plan_features:
                feature_code = item.get("feature_code")
                if not feature_code:
                    continue
                feature = SubscriptionFeature.objects.filter(code=feature_code).first()
                if not feature:
                    continue
                PlanFeature.objects.update_or_create(
                    plan_version=plan_version,
                    feature=feature,
                    defaults={
                        "is_enabled": bool(item.get("is_enabled", False)),
                        "access_level": item.get(
                            "access_level", FeatureAccessLevelChoices.FULL
                        ),
                        "limit_value": item.get("limit_value"),
                        "metadata": item.get("metadata") or {},
                    },
                )

        if limits is not None:
            for item in limits:
                metric_code = item.get("metric_code")
                if not metric_code:
                    continue
                PlanLimit.objects.update_or_create(
                    plan_version=plan_version,
                    metric_code=metric_code,
                    defaults={
                        "included_quantity": item.get("included_quantity", 0),
                        "min_quantity": item.get("min_quantity", 0),
                        "max_quantity": item.get("max_quantity"),
                        "overage_unit_price": item.get("overage_unit_price", 0),
                        "enforcement_mode": item.get(
                            "enforcement_mode",
                            LimitEnforcementModeChoices.SOFT_WARNING,
                        ),
                        "stripe_overage_price_id": item.get("stripe_overage_price_id"),
                    },
                )

        return plan_version
