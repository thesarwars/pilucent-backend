from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, get_object_or_404

from leaveio.models import LeaveType

from leaveio.choices import LeaveStatusChoices

from weapi.django_rest.serializers.leaves.leave_type import (
    PrivateLeaveTypeListSerializer,
    PrivateLeaveTypeDetailsSerializer
)

class PrivateWeLeaveTypeList(ListCreateAPIView):
    serializer_class = PrivateLeaveTypeListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["name", "display_name", "definition"]
    filterset_fields = ["status", "is_active"]

    def get_queryset(self):
        return LeaveType.objects.get_status_all().filter(
			company=self.request.user.get_active_company()
		)
    

class PrivateWeLeaveTypeDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateLeaveTypeDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            LeaveType.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = LeaveStatusChoices.REMOVED
        instance.save()