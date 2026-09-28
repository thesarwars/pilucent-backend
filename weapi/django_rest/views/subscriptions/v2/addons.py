from rest_framework import response, status, views

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.services.addon_service import AddOnService


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeSubscriptionAddOnList(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request):
        company = request.user.get_active_company()
        return response.Response(AddOnService.list_for_company(company))


class PrivateWeSubscriptionAddOnPurchase(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def post(self, request):
        company = request.user.get_active_company()
        addon_uid = request.data.get("addon_uid")
        if not addon_uid:
            return response.Response(
                {"error": "addon_uid is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = AddOnService.purchase_for_active_subscription(
                company=company,
                user=request.user,
                addon_uid=addon_uid,
                quantity=int(request.data.get("quantity", 1)),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result, status=status.HTTP_201_CREATED)
