from auditlog.models import LogEntry

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import ListAPIView
from rest_framework import filters

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import AuditLogDateRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription

from ..serializers.audit_logs import PrivateWeAuditLogListSerializer


class PrivateWeAuditLogList(ListAPIView):
    serializer_class = PrivateWeAuditLogListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_audit_log"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        AuditLogDateRangeFilter,
    ]
    ordering_fields = ["timestamp"]
    search_fields = ["actor__name"]
    filterset_fields = ["actor__name"]

    def get_queryset(self):
        user = self.request.user
        queryset = LogEntry.objects.filter(
            actor_id__in=user.companyuser_set.values_list("user_id", flat=True)
        )
        return queryset
