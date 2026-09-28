from rest_framework import filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from wirehouseio.models import Warehouse

from wirehouseio.choicess import WarehouseStatusChoices

from ..serializers.warehouses import (
    PrivateWeWarehouseListSerializer,
    PrivateWeWarehouseDetailsSerializer,
)

class PrivateWeWarehouseListCreateView(ListCreateAPIView):
    serializer_class = PrivateWeWarehouseListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_warehouse"
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    ordering_fields = ["created_at"]
    search_fields = ["title", "short_name"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return Warehouse.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeWarehouseRetrieveUpdateView(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeWarehouseDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_warehouse"

    def get_object(self):
        return get_object_or_404(
            Warehouse.objects.get_status_all().filter(
                company=self.request.user.get_active_company()
            ),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = WarehouseStatusChoices.REMOVED
        instance.save()
