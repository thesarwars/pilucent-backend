from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, get_object_or_404

from leaveio.models import LeaveEncashment, LeaveEncashmentItem
from leaveio.choices import LeaveEncashmentStatusChoices

from weapi.django_rest.serializers.leaves.leave_encashment import (
    LeaveEncashmentSerializer,
    LeaveEncashmentDetailUpdateSerializer,
    LeaveEncashmentItemSerializer,
    LeaveEncashmentItemDetailSerializer,
)


# List/Create LeaveEncashmentItem
class PrivateWeLeaveEncashmentItemListCreateView(ListCreateAPIView):
    serializer_class = LeaveEncashmentItemSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return LeaveEncashmentItem.objects.filter(
            encashment__company=self.request.user.get_active_company()
        )


# Retrieve/Update/Delete LeaveEncashmentItem
class PrivateWeLeaveEncashmentItemDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = LeaveEncashmentItemDetailSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            LeaveEncashmentItem.objects.all(),
            encashment__company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )


class PrivateWeLeaveEncashmentList(ListCreateAPIView):
    serializer_class = LeaveEncashmentSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["encashment_date", "created_at"]
    search_fields = ["employee__name"]
    filterset_fields = ["status", "employee", "company"]

    def get_queryset(self):
        return LeaveEncashment.objects.filter(
            company=self.request.user.get_active_company(),
            status = LeaveEncashmentStatusChoices.ACTIVE
        )


class PrivateWeLeaveEncashmentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = LeaveEncashmentDetailUpdateSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            LeaveEncashment.objects.select_related('employee', 'leave_balance').prefetch_related('items__leave_type', 'items__leave_allocation'),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = LeaveEncashmentStatusChoices.REMOVED
        instance.save()


