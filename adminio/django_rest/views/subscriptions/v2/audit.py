from rest_framework import generics

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from subscriptionio.services.admin_audit_service import AdminAuditService


class AdminSubscriptionAuditLogList(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminAuditService.get_events_queryset(
            search=self.request.query_params.get("search"),
            category=self.request.query_params.get("category"),
        )

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminAuditService.serialize_events,
        )
