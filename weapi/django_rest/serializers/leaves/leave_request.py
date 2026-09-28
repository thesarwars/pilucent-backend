from rest_framework.serializers import ModelSerializer, SlugRelatedField, ValidationError
from leaveio.models import LeaveRequest, LeaveType
from leaveio.django_rest.serializers.common import (
    PrivateLeaveRequestSlimSerializer,
    PrivateLeaveTypeSlimSerializer,
)
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from companyio.django_rest.serializers.common import (
    PrivateCompanyShiftSlimSerializer,
)
from employeeio.models import Employee
from employeeio.choices import EmployeeStatusChoices


class PrivateLeaveRequestListSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    leave_type = PrivateLeaveTypeSlimSerializer(read_only=True)
    leave_type_uid = SlugRelatedField(
        slug_field="uid",
        queryset=LeaveType.objects.get_status_all(),
        write_only=True,
        required=True,
    )
    assigned_to = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    assigned_to_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all().exclude(status=EmployeeStatusChoices.REMOVED),
        write_only=True,
        required=False,
        allow_null=True,
    )
    approved_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "uid",
            "employee",
            "leave_type",
            "leave_type_uid",
            "from_date",
            "to_date",
            "total_days",
            "status",
            "note",
            "assigned_to",
            "assigned_to_uid",
            "approved_by",
            "employee_shift",
            "is_active",
        ]
        read_only_fields = ["uid", "leave_type", "assigned_to"]

    def validate(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        user = self.context["request"].user
        employee = user.get_employee()
        employee_shift = employee.shift
        if not employee_shift:
            raise ValidationError("You dont have any shift")
        validated_data["employee_shift"] = employee_shift
        return super().validate(validated_data)

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        employee = user.get_employee()
        validated_data["leave_type"] = validated_data.pop("leave_type_uid")
        validated_data["assigned_to"] = validated_data.pop("assigned_to_uid", None)
        validated_data["employee"] = employee
        return super().create(validated_data)


class LeaveRequestStatusUpdateSerializer(ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = ["status"]


class PrivateLeaveRequestDetailsSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    leave_type = PrivateLeaveTypeSlimSerializer(read_only=True)
    leave_type_uid = SlugRelatedField(
        slug_field="uid",
        queryset=LeaveType.objects.get_status_all(),
        write_only=True,
        required=True,
    )
    assigned_to = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    assigned_to_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all().exclude(status=EmployeeStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )
    approved_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "uid",
            "employee",
            "leave_type",
            "leave_type_uid",
            "from_date",
            "to_date",
            "total_days",
            "status",
            "note",
            "assigned_to",
            "assigned_to_uid",
            "employee_shift",
            "approved_by",
            "is_active",
        ]
        read_only_fields = ["uid", "leave_type", "assigned_to"]

    def validate(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        return super().validate(validated_data)

    def update(self, instance, validated_data):
        if "leave_type_uid" in validated_data:
            validated_data["leave_type"] = validated_data.pop("leave_type_uid")
        if "assigned_to_uid" in validated_data:
            validated_data["assigned_to"] = validated_data.pop("assigned_to_uid")
        validated_data["employee"] = self.context["request"].user.get_employee()
        return super().update(instance, validated_data)
