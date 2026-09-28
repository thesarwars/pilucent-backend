from dataclasses import dataclass, field
from typing import Any

from django.db.models import Q

from adminio.django_rest.helpers.group_permissions import _resolve_required_permissions

from companyio.models import CompanyUser

from subscriptionio.models import SubscriptionFeature
from subscriptionio.services.entitlement_service import EntitlementService


@dataclass
class AccessResult:
    allowed: bool
    denied_by: str | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AccessPolicy:
    PERMISSION_DENIED_MESSAGE = (
        "Your role doesn't have power for this action, gain power and try again."
    )

    @classmethod
    def _user_has_permissions(cls, user, required_permissions) -> bool:
        if not required_permissions:
            return False

        required_ids = [permission.id for permission in required_permissions]
        if user.groups.filter(permissions__id__in=required_ids).exists():
            return True

        return (
            CompanyUser.objects.filter(
                user=user,
                company=user.get_active_company(),
            )
            .filter(
                Q(roles__permission__id__in=required_ids)
                | Q(permission__id__in=required_ids)
            )
            .exists()
        )

    @classmethod
    def check_subscription(cls, user, feature_identifier: str) -> AccessResult:
        company = user.get_active_company() if user and user.is_authenticated else None
        result = EntitlementService.check_feature(company, feature_identifier)
        if result.allowed:
            return AccessResult(allowed=True)
        return AccessResult(
            allowed=False,
            denied_by="subscription",
            message=result.message,
            metadata=result.upgrade_metadata,
        )

    @classmethod
    def check_permission(cls, user, view, request) -> AccessResult:
        if not user or not user.is_authenticated:
            return AccessResult(
                allowed=False,
                denied_by="permission",
                message=cls.PERMISSION_DENIED_MESSAGE,
            )
        if user.is_superuser or getattr(user, "is_admin", False):
            return AccessResult(allowed=True)

        required = _resolve_required_permissions(view, request)
        if not required:
            return AccessResult(
                allowed=False,
                denied_by="permission",
                message=cls.PERMISSION_DENIED_MESSAGE,
            )

        if cls._user_has_permissions(user, required):
            return AccessResult(allowed=True)

        return AccessResult(
            allowed=False,
            denied_by="permission",
            message=cls.PERMISSION_DENIED_MESSAGE,
        )

    @classmethod
    def check(cls, user, view, request) -> AccessResult:
        feature_identifier = getattr(view, "required_feature", None)
        if feature_identifier:
            subscription_result = cls.check_subscription(user, feature_identifier)
            if not subscription_result.allowed:
                return subscription_result

        return cls.check_permission(user, view, request)

    @classmethod
    def _collect_user_permissions(cls, user, company) -> set[str]:
        permission_codenames: set[str] = set()
        if not user or not user.is_authenticated:
            return permission_codenames

        permission_codenames.update(
            user.user_permissions.values_list("codename", flat=True)
        )
        permission_codenames.update(
            user.groups.values_list("permissions__codename", flat=True)
        )
        if company:
            company_user = (
                CompanyUser.objects.filter(user=user, company=company)
                .prefetch_related("roles__permission", "permission")
                .first()
            )
            if company_user:
                permission_codenames.update(
                    company_user.permission.values_list("codename", flat=True)
                )
                permission_codenames.update(
                    company_user.roles.values_list("permission__codename", flat=True)
                )
        return permission_codenames

    @classmethod
    def _effective_feature_access(
        cls, plan_enabled: bool, permission_codenames: list, user_permissions: set[str]
    ) -> bool:
        if not plan_enabled:
            return False
        if not permission_codenames:
            return True
        return bool(user_permissions.intersection(permission_codenames))

    @classmethod
    def build_access_manifest(cls, user) -> dict[str, Any]:
        company = user.get_active_company() if user and user.is_authenticated else None
        entitlements = EntitlementService.get_entitlements(company)
        user_permissions = cls._collect_user_permissions(user, company)
        plan_features = entitlements.get("features", {})

        catalog = SubscriptionFeature.objects.filter(is_active=True).select_related(
            "module"
        )
        effective_features = {}
        feature_permissions = {}

        for catalog_feature in catalog:
            plan_enabled = plan_features.get(catalog_feature.code)
            if plan_enabled is None and catalog_feature.legacy_field:
                plan_enabled = plan_features.get(catalog_feature.legacy_field, False)

            effective = cls._effective_feature_access(
                bool(plan_enabled),
                catalog_feature.permission_codenames or [],
                user_permissions,
            )
            effective_features[catalog_feature.code] = effective
            if catalog_feature.permission_codenames:
                feature_permissions[catalog_feature.code] = (
                    catalog_feature.permission_codenames
                )

        return {
            "subscription_status": entitlements.get("subscription_status"),
            "plan_title": entitlements.get("plan_title"),
            "plan_version": entitlements.get("plan_version"),
            "features": plan_features,
            "limits": entitlements.get("limits", {}),
            "permissions": sorted(user_permissions),
            "feature_permissions": feature_permissions,
            "effective_features": effective_features,
        }
