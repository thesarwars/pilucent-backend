from rest_framework import filters
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from employeeio.models import Employee
from leaveio.models import LeaveType
from leaveio.choices import LeaveBalanceStatusChoices
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from leaveio.models import LeaveBalance, EmployeeLeaveAllocation
from weapi.django_rest.serializers.leaves.leave_balance import (
    LeaveBalanceCreateSerializer,
    LeaveBalanceDetailUpdateSerializer,
    EmployeeLeaveAllocationSerializer,
    EmployeeLeaveAllocationDetailUpdateSerializer,
)
from leaveio.choices import LeaveStatusChoices


class PrivateWeLeaveBalanceListCreateView(ListCreateAPIView):
    serializer_class = LeaveBalanceCreateSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return LeaveBalance.objects.filter(
            company=self.request.user.get_active_company(),
            status=LeaveBalanceStatusChoices.ACTIVE
        )


class PrivateWeLeaveBalanceDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = LeaveBalanceDetailUpdateSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            LeaveBalance.objects.all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )
        
    def perform_destroy(self, instance):
        instance.status = LeaveBalanceStatusChoices.REMOVED
        instance.save()


class PrivateWeEmployeeLeaveAllocationListCreateView(ListCreateAPIView):
    serializer_class = EmployeeLeaveAllocationSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["employee__first_name", "employee__last_name", "leave_type__name"]
    filterset_fields = ["employee__uid", "leave_type__uid", "leave_balance__uid"]

    def get_queryset(self):
        return EmployeeLeaveAllocation.objects.filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeEmployeeLeaveAllocationDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = EmployeeLeaveAllocationDetailUpdateSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            EmployeeLeaveAllocation.objects.all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

# Endpoint: List all employees with all leave types and their allocations
class CompanyEmployeeLeaveTypeListView(APIView):
    # permission_classes = [IsGroupPermission]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        employees = Employee.objects.filter(user__companyuser__company=company)
        leave_types = LeaveType.objects.filter(
            company=company, status=LeaveStatusChoices.ACTIVE
        )
        data = []
        for emp in employees:
            leave_type_data = []
            for lt in leave_types:
                leave_type_data.append(
                    {
                        "leaveTypeUid": str(lt.uid),
                        "leaveTypeName": lt.display_name or lt.name,
                        "maximum_allocation": lt.maximum_allocation,
                    }
                )
            # Compose employeeName from first_name and last_name if available
            first_name = getattr(emp, "first_name", "")
            last_name = getattr(emp, "last_name", "")
            if first_name or last_name:
                employee_name = f"{first_name} {last_name}".strip()
            else:
                # fallback: use user.name if available, else empty string
                employee_name = getattr(emp.user, "name", "")
            data.append(
                {
                    "employeeUid": str(emp.uid),
                    "employeeName": employee_name,
                    "leaveTypes": leave_type_data,
                }
            )
        return Response({"status": 200, "msg": "Success", "data": data}, status=200)
