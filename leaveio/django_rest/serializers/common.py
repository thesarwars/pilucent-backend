
from rest_framework.serializers import ModelSerializer
from leaveio.models import (
    LeaveType,
    LeaveRequest,
    EmployeeLeaveAllocation,
    LeaveBalance,
    LeaveEncashment,
    LeaveEncashmentItem,
)

class LeaveEncashmentBaseSerializer(ModelSerializer):
    class Meta:
        model = LeaveEncashment
        fields = [
            "employee",
            "encashment_date",
            "leave_balance",
            "total_encashment_amount",
            "status",
            "created_by",
            "company",
        ]
        read_only_fields = fields

class PrivateLeaveEncashmentSlimSerializer(LeaveEncashmentBaseSerializer):
    class Meta:
        model = LeaveEncashmentBaseSerializer.Meta.model
        fields = ["uid"] + LeaveEncashmentBaseSerializer.Meta.fields
        read_only_fields = fields

class PublicLeaveEncashmentSlimSerializer(LeaveEncashmentBaseSerializer):
    class Meta:
        model = LeaveEncashmentBaseSerializer.Meta.model
        fields = ["slug"] + LeaveEncashmentBaseSerializer.Meta.fields
        read_only_fields = fields

class LeaveEncashmentItemBaseSerializer(ModelSerializer):
    class Meta:
        model = LeaveEncashmentItem
        fields = [
            "leave_type",
            "leave_allocation",
            "leave_balance",
            "actual_encashable_days",
            "encashment_days",
            "amount_per_day",
            "total_amount",
        ]
        read_only_fields = fields

class PrivateLeaveEncashmentItemSlimSerializer(LeaveEncashmentItemBaseSerializer):
    class Meta:
        model = LeaveEncashmentItemBaseSerializer.Meta.model
        fields = ["uid"] + LeaveEncashmentItemBaseSerializer.Meta.fields
        read_only_fields = fields

class PublicLeaveEncashmentItemSlimSerializer(LeaveEncashmentItemBaseSerializer):
    class Meta:
        model = LeaveEncashmentItemBaseSerializer.Meta.model
        fields = ["slug"] + LeaveEncashmentItemBaseSerializer.Meta.fields
        read_only_fields = fields



class LeaveTypeBaseSerializer(ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "name",
            "display_name",
            "definition",
            "color",
            "max_consecutive_allowed",
            "leave_type",
        ]
        read_only_fields = fields


class PrivateLeaveTypeSlimSerializer(LeaveTypeBaseSerializer):
    class Meta:
        model = LeaveTypeBaseSerializer.Meta.model
        fields = ["uid"] + LeaveTypeBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicLeaveTypeSlimSerializer(LeaveTypeBaseSerializer):
    class Meta:
        model = LeaveTypeBaseSerializer.Meta.model
        fields = ["slug"] + LeaveTypeBaseSerializer.Meta.fields
        read_only_fields = fields


# LeaveRequest Slim Serializers
class LeaveRequestBaseSerializer(ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = [
            "leave_type",
            "from_date",
            "to_date",
            "total_days",
            "status",
            "note",
            "assigned_to",
            "approved_by",
            "is_active",
        ]
        read_only_fields = fields


class PrivateLeaveRequestSlimSerializer(LeaveRequestBaseSerializer):
    class Meta:
        model = LeaveRequestBaseSerializer.Meta.model
        fields = ["uid"] + LeaveRequestBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicLeaveRequestSlimSerializer(LeaveRequestBaseSerializer):
    class Meta:
        model = LeaveRequestBaseSerializer.Meta.model
        fields = ["slug"] + LeaveRequestBaseSerializer.Meta.fields
        read_only_fields = fields


class PrivateWeEmployeeLeaveAllocationSlimSerializer(ModelSerializer):
    class Meta:
        model = EmployeeLeaveAllocation
        fields = [
            "uid",
            "employee",
            "leave_type",
            "leave_year",
            "allocated_days",
        ]
        read_only_fields = ["uid", "allocated_days", "employee", "leave_type"]


class PrivateWeLeaveBalanceSlimSerializer(ModelSerializer):
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
        ]
        read_only_fields = [
            "uid",
            "title",
            "leave_year",
            "from_date",
            "to_date",
            "status",
            "is_active",
        ]
