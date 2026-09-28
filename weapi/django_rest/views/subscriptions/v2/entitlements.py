from rest_framework import response, status, views
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.services.access_policy import AccessPolicy
from subscriptionio.services.entitlement_service import EntitlementService


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeEntitlementCheck(views.APIView):
    """Check whether the active company has a subscription feature enabled."""

    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def post(self, request, *args, **kwargs):
        feature = request.data.get("feature") or request.data.get("feature_code")
        if not feature:
            return response.Response(
                {"error": "feature is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company = request.user.get_active_company()
        result = EntitlementService.check_feature(company, feature)
        return response.Response(
            {
                "allowed": result.allowed,
                "feature": result.feature_code,
                "denied_by": result.denied_by,
                "message": result.message,
                "upgrade_metadata": result.upgrade_metadata,
            }
        )


class PrivateWeAccessManifest(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        return Response(AccessPolicy.build_access_manifest(request.user))
