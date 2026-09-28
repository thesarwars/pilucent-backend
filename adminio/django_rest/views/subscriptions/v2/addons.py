from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from subscriptionio.models import SubscriptionAddOn
from subscriptionio.services.admin_addon_service import AdminAddOnService


class AdminSubscriptionAddOnListCreate(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminAddOnService.get_addons_queryset(
            status=self.request.query_params.get("status"),
            search=self.request.query_params.get("search"),
        )

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminAddOnService.serialize_addons,
        )

    def post(self, request):
        try:
            result = AdminAddOnService.create_addon(dict(request.data))
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result, status=status.HTTP_201_CREATED)


class AdminSubscriptionAddOnDetail(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, uid):
        add_on = get_object_or_404(
            SubscriptionAddOn.objects.prefetch_related("applies_to_subscriptions"),
            uid=uid,
        )
        return response.Response(AdminAddOnService.get_addon(add_on))

    def patch(self, request, uid):
        add_on = get_object_or_404(SubscriptionAddOn, uid=uid)
        try:
            result = AdminAddOnService.update_addon(add_on, dict(request.data))
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)

    def delete(self, request, uid):
        add_on = get_object_or_404(SubscriptionAddOn, uid=uid)
        result = AdminAddOnService.delete_addon(add_on)
        return response.Response(result)
