from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from subscriptionio.models import Subscription
from subscriptionio.services.admin_plan_catalog_service import AdminPlanCatalogService


class AdminSubscriptionPlanListCreate(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminPlanCatalogService.get_plans_queryset()

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminPlanCatalogService.serialize_plans,
        )

    def post(self, request, *args, **kwargs):
        try:
            result = AdminPlanCatalogService.create_plan(dict(request.data))
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result, status=status.HTTP_201_CREATED)


class AdminSubscriptionPlanDetail(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, uid):
        subscription = get_object_or_404(Subscription, uid=uid)
        return response.Response(AdminPlanCatalogService.get_plan(subscription))

    def patch(self, request, uid):
        subscription = get_object_or_404(Subscription, uid=uid)
        try:
            result = AdminPlanCatalogService.update_plan(subscription, dict(request.data))
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)

    def delete(self, request, uid):
        subscription = get_object_or_404(Subscription, uid=uid)
        result = AdminPlanCatalogService.archive_plan(subscription)
        return response.Response(result)
