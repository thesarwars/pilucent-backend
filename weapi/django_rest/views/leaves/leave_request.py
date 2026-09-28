from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status

from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from leaveio.models import LeaveRequest, LeaveRequests, LeaveApproval
from leaveio.models import EmployeeLeaveAllocation

from leaveio.choices import EmployeeLeaveRequestStatusChoices

from weapi.django_rest.serializers.leaves.leave_request import (
    PrivateLeaveRequestListSerializer,
    PrivateLeaveRequestDetailsSerializer,
    LeaveRequestStatusUpdateSerializer,
)


class PrivateWeLeaveRequestStatusUpdate(APIView):
    permission_classes = [IsGroupPermission]
    # Named explicitly: this view gives the permission resolver no model to
    # infer from, so it returned [] (or raised) and refused every user who is
    # not a superuser or `is_admin`. See adminio/tests_permission_resolution.py.
    required_permissions = ["change_leaveapproval"]
    queryset = LeaveApproval.objects.all()

    def patch(self, request, uid):
        leave_request = get_object_or_404(
            LeaveRequest.objects.get_status_all(),
            company=request.user.get_active_company(),
            uid=uid,
        )
        status_to_update = request.data.get("status")
        # Only check allocation if status is being set to APPROVED
        if status_to_update == EmployeeLeaveRequestStatusChoices.APPROVED:
            if leave_request.status == EmployeeLeaveRequestStatusChoices.APPROVED:
                return Response(
                    {
                        "msg": "Leave request is already approved.",
                        "error": True,
                    },
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

            allocation = EmployeeLeaveAllocation.objects.filter(
                employee=leave_request.employee,
                leave_type=leave_request.leave_type,
                company=leave_request.company,
                leave_year=(
                    leave_request.from_date.year if leave_request.from_date else None
                ),
            ).first()
            if not allocation:
                return Response(
                    {
                        "detail": "No leave allocation found for this employee and leave type."
                    },
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            if leave_request.total_days is None or allocation.allocated_days is None:
                return Response(
                    {"detail": "Leave request or allocation days missing."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            if leave_request.total_days > allocation.allocated_days:
                return Response(
                    {"detail": "Requested leave days exceed allocated days."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            # Update allocation used days
            allocation.used_days = (allocation.used_days or 0) + leave_request.total_days
            allocation.save()
        serializer = LeaveRequestStatusUpdateSerializer(
            leave_request, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"msg": "Leave request status updated successfully.", **serializer.data},
            status=drf_status.HTTP_200_OK,
        )


class PrivateWeLeaveRequestList(ListCreateAPIView):
    serializer_class = PrivateLeaveRequestListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["note", "leave_type__name", "employee__name", "employee__uid"]
    filterset_fields = ["status", "is_active", "employee__uid", "leave_type__uid"]

    def get_queryset(self):
        return LeaveRequests.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeLeaveRequestDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateLeaveRequestDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            LeaveRequests.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = EmployeeLeaveRequestStatusChoices.REMOVED
        instance.save()
