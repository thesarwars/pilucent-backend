from django.db import transaction
from rest_framework import serializers
from rest_framework.fields import JSONField
from leaveio.models import LeaveBalance, EmployeeLeaveAllocation, LeaveType
from employeeio.models import Employee
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from leaveio.django_rest.serializers.common import (
    PrivateLeaveTypeSlimSerializer,
    PrivateWeLeaveBalanceSlimSerializer,
)


class EmployeeLeaveAllocationSerializer(serializers.ModelSerializer):
    employee_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all(),
        source="employee",
        write_only=True,
    )
    leave_type_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=LeaveType.objects.all(),
        source="leave_type",
        write_only=True,
    )
    leave_balance_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=LeaveBalance.objects.all(),
        source="leave_balance",
        write_only=True,
        required=False,
        allow_null=True,
    )
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    leave_type = PrivateLeaveTypeSlimSerializer(read_only=True)
    leave_balance = PrivateWeLeaveBalanceSlimSerializer(read_only=True)

    class Meta:
        model = EmployeeLeaveAllocation
        fields = [
            "uid",
            "employee_uid",
            "leave_type_uid",
            "leave_balance_uid",
            "leave_year",
            "allocated_days",
            "used_days",
            "opening_balance",
            "allocated",
            "used",
            "encashed",
            "adjusted",
            "employee",
            "leave_type",
            "leave_balance",
            "available_days",
            "available_balance",
        ]
        read_only_fields = ["uid"]


class EmployeeLeaveAllocationDetailUpdateSerializer(serializers.ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    leave_type = PrivateLeaveTypeSlimSerializer(read_only=True)
    leave_balance = PrivateWeLeaveBalanceSlimSerializer(read_only=True)

    class Meta:
        model = EmployeeLeaveAllocation
        fields = [
            "uid",
            "employee",
            "leave_type",
            "leave_balance",
            "leave_year",
            "allocated_days",
            "opening_balance",
            "allocated",
            "used",
            "encashed",
            "adjusted",
        ]
        read_only_fields = [
            "uid",
            "employee",
        ]


class LeaveBalanceCreateSerializer(serializers.ModelSerializer):
    allocations = JSONField(
        required=False,
        write_only=True,
        help_text="List of allocations per employee, each with allocation_item array.",
    )
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = LeaveBalance
        fields = [
            "uid",
            "title",
            "leave_year",
            "from_date",
            "to_date",
            "status",
            "is_active",
            "created_by",
            "allocations",
        ]
        read_only_fields = ["uid"]

    @transaction.atomic
    def create(self, validated_data):
        allocations_data = validated_data.pop("allocations", [])
        request = self.context["request"]
        user = request.user
        validated_data["company"] = user.get_active_company()
        validated_data["created_by"] = user.get_employee()
        leave_balance = super().create(validated_data)
        allocation_objs = []
        for alloc in allocations_data:
            employee = Employee.objects.get(
                    uid=alloc["employee_uid"], company=self.context["request"].user.get_active_company()
                )
            allocation_items = alloc.get("allocation_item", [])
            for item in allocation_items:
                leave_type = LeaveType.objects.get(uid=item["leave_type_uid"])
                allocation_objs.append(
                    EmployeeLeaveAllocation(
                        employee=employee,
                        leave_type=leave_type,
                        leave_balance=leave_balance,
                        leave_year=alloc.get("leave_year", leave_balance.leave_year),
                        allocated_days=item.get("allocated_days", 0),
                        opening_balance=alloc.get("opening_balance", 0.00),
                        allocated=alloc.get("allocated", 0.00),
                        used=alloc.get("used", 0.00),
                        encashed=alloc.get("encashed", 0.00),
                        adjusted=alloc.get("adjusted", 0.00),
                        company=leave_balance.company,
                        created_by=user.get_employee(),
                    )
                )
        if allocation_objs:
            EmployeeLeaveAllocation.objects.bulk_create(allocation_objs)
        return leave_balance


class LeaveBalanceDetailUpdateSerializer(serializers.ModelSerializer):
    allocations = EmployeeLeaveAllocationDetailUpdateSerializer(
        many=True, read_only=True
    )
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = LeaveBalance
        fields = [
            "uid",
            "title",
            "leave_year",
            "from_date",
            "to_date",
            "status",
            "is_active",
            "created_by",
            "allocations",
            # 'leave_type' is not a model field, so do not include it here
        ]
        read_only_fields = ["uid", "allocations"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Group allocations by employee, each with leaveTypes array
        employee_map = {}
        for alloc in instance.allocations.all():
            emp = alloc.employee
            emp_uid = str(emp.uid)
            emp_name = getattr(emp, "full_name", "")
            if not emp_name:
                emp_name = getattr(getattr(emp, "user", None), "name", "")
            if emp_uid not in employee_map:
                employee_map[emp_uid] = {
                    "employeeUid": emp_uid,
                    "employeeName": emp_name,
                    "leaveTypes": [],
                }
            lt = alloc.leave_type
            employee_map[emp_uid]["leaveTypes"].append(
                {
                    "uid": str(alloc.uid),
                    "leaveTypeUid": str(lt.uid),
                    "totalDays": alloc.allocated_days,
                    "leaveTypeName": getattr(lt, "display_name", ""),
                    "max_consecutive_allowed": getattr(
                        lt, "max_consecutive_allowed", 0
                    ),
                    "leave_type": getattr(lt, "leave_type", ""),
                    "maximum_allocation": getattr(lt, "maximum_allocation", 0),
                }
            )
        data["employee_leave_types"] = list(employee_map.values())
        return data

    def update(self, instance, validated_data):
        # Only update LeaveBalance fields, ignore allocations
        validated_data.pop("allocations", None)
        return super().update(instance, validated_data)
