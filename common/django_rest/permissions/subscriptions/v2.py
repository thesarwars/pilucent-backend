from rest_framework import permissions

from subscriptionio.services.entitlement_service import EntitlementService


class HaveSubscriptionV2(permissions.IsAuthenticated):
    """Entitlement-engine subscription gate (plan versions + feature catalogue)."""

    message = EntitlementService.INACTIVE_MESSAGE

    def _has_subscription(self, request, view):
        user = request.user
        if user.is_anonymous:
            return False

        company = user.get_active_company()
        feature_identifier = getattr(view, "required_feature", None)
        if not feature_identifier:
            return False

        result = EntitlementService.check_feature(company, feature_identifier)
        if not result.allowed:
            self.message = result.message or EntitlementService.INACTIVE_MESSAGE
            return False

        return True

    def has_permission(self, request, view):
        return self._has_subscription(request, view)

    def has_object_permission(self, request, view, obj):
        return self._has_subscription(request, view)
