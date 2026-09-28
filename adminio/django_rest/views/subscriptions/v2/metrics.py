from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from subscriptionio.models import SubscriptionBillableMetric
from subscriptionio.services.admin_metric_service import AdminMetricService


class AdminSubscriptionMetricListCreate(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        include_inactive = self.request.query_params.get("include_inactive") == "true"
        return AdminMetricService.get_metrics_queryset(include_inactive=include_inactive)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginated = self.paginated_list_response(
            queryset,
            AdminMetricService.serialize_metrics,
            enforcement_modes=AdminMetricService.list_enforcement_modes(),
        )
        if "results" in paginated.data:
            paginated.data["metrics"] = paginated.data.pop("results")
        return paginated

    def post(self, request, *args, **kwargs):
        try:
            result = AdminMetricService.create_metric(dict(request.data))
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result, status=status.HTTP_201_CREATED)


class AdminSubscriptionMetricDetail(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, uid):
        metric = get_object_or_404(SubscriptionBillableMetric, uid=uid)
        return response.Response(AdminMetricService.get_metric(metric))

    def patch(self, request, uid):
        metric = get_object_or_404(SubscriptionBillableMetric, uid=uid)
        try:
            result = AdminMetricService.update_metric(metric, dict(request.data))
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)

    def delete(self, request, uid):
        metric = get_object_or_404(SubscriptionBillableMetric, uid=uid)
        result = AdminMetricService.archive_metric(metric)
        return response.Response(result)
