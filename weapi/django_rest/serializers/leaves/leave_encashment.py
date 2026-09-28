from rest_framework.serializers import ModelSerializer, SlugRelatedField
from leaveio.models import LeaveEncashment, LeaveEncashmentItem, LeaveBalance, LeaveType, EmployeeLeaveAllocation
from employeeio.django_rest.serializers.common import PrivateCompanyEmployeeSlimSerializer
from leaveio.django_rest.serializers.common import PrivateWeLeaveBalanceSlimSerializer, PrivateLeaveTypeSlimSerializer
from employeeio.models import Employee

from rest_framework import serializers

class LeaveEncashmentItemSerializer(ModelSerializer):
    leave_type = PrivateLeaveTypeSlimSerializer(read_only=True)
    leave_type_uid = SlugRelatedField(
        slug_field="uid",
        queryset=LeaveType.objects.get_status_all(),
        source="leave_type",
        write_only=True,
        required=True,
    )
    leave_allocation = PrivateWeLeaveBalanceSlimSerializer(read_only=True)
    leave_allocation_uid = SlugRelatedField(
        slug_field="uid",
        queryset=EmployeeLeaveAllocation.objects.all(),
        source="leave_allocation",
        write_only=True,
        required=False,
        allow_null=True,
    )
    leave_balance = serializers.DecimalField(max_digits=19, decimal_places=3)

    class Meta:
        model = LeaveEncashmentItem
        fields = [
            "uid",
            "leave_type",
            "leave_type_uid",
            "leave_allocation",
            "leave_allocation_uid",
            "leave_balance",
            "actual_encashable_days",
            "encashment_days",
            "amount_per_day",
            "total_amount",
        ]
        read_only_fields = ["uid"]


class LeaveEncashmentItemDetailSerializer(ModelSerializer):
    leave_type = PrivateLeaveTypeSlimSerializer(read_only=True)
    leave_type_uid = SlugRelatedField(
        slug_field="uid",
        queryset=LeaveType.objects.get_status_all(),
        source="leave_type",
        write_only=True,
        required=True,
    )
    leave_allocation = PrivateWeLeaveBalanceSlimSerializer(read_only=True)
    leave_allocation_uid = SlugRelatedField(
        slug_field="uid",
        queryset=EmployeeLeaveAllocation.objects.all(),
        source="leave_allocation",
        write_only=True,
        required=False,
        allow_null=True,
    )
    
    class Meta:
        model = LeaveEncashmentItem
        fields = [
            "uid",
            "leave_type",
            "leave_type_uid",
            "leave_allocation",
            "leave_allocation_uid",
            "leave_balance",
            "actual_encashable_days",
            "encashment_days",
            "amount_per_day",
            "total_amount",
        ]
        read_only_fields = ["uid", "leave_type", "leave_allocation"]


class LeaveEncashmentSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all(),
        source="employee",
        write_only=True,
        required=True,
    )
    leave_balance = PrivateWeLeaveBalanceSlimSerializer(read_only=True)
    leave_balance_uid = SlugRelatedField(
        slug_field="uid",
        queryset=LeaveBalance.objects.get_status_all(),
        source="leave_balance",
        write_only=True,
        required=True,
    )
    items = LeaveEncashmentItemSerializer(many=True, required=False, write_only=True, help_text="List of encashment items per leave type.")
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = LeaveEncashment
        fields = [
            "uid",
            "employee",
            "employee_uid",
            "encashment_date",
            "leave_balance",
            "leave_balance_uid",
            "total_encashment_amount",
            "status",
            "created_by",
            "company",
            "items",
        ]
        read_only_fields = ["uid", "company", "created_by"]

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        request = self.context.get("request")
        user = request.user if request else None
        if user:
            validated_data["company"] = user.get_active_company()
            validated_data["created_by"] = user.get_employee()
        encashment = super().create(validated_data)
        for item_data in items_data:
            LeaveEncashmentItem.objects.create(encashment=encashment, **item_data)
        return encashment


class LeaveEncashmentDetailUpdateSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all(),
        source="employee",
        write_only=True,
        required=True,
    )
    leave_balance = PrivateWeLeaveBalanceSlimSerializer(read_only=True)
    items = LeaveEncashmentItemDetailSerializer(many=True, required=False)

    class Meta:
        model = LeaveEncashment
        fields = [
            "uid",
            "employee",
            "employee_uid",
            "encashment_date",
            "leave_balance",
            "total_encashment_amount",
            "status",
            "created_by",
            "company",
            "items",
        ]
        read_only_fields = ["uid", "created_by", "company"]

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        # Update LeaveEncashment fields
        instance = super().update(instance, validated_data)
        if items_data is not None:
            for item in items_data:
                uid = item.get("uid", None)
                if uid:
                    # Update existing item
                    try:
                        encashment_item = instance.items.get(uid=uid)
                        for attr, value in item.items():
                            if attr != "uid":
                                setattr(encashment_item, attr, value)
                        encashment_item.save()
                    except LeaveEncashmentItem.DoesNotExist:
                        continue  # Or raise error if you want
                else:
                    # Create new item
                    LeaveEncashmentItem.objects.create(encashment=instance, **item)
        return instance