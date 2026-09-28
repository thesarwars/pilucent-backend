

from rest_framework.serializers import ModelSerializer, SlugRelatedField
from leaveio.models import LeaveType
from leaveio.django_rest.serializers.common import PrivateLeaveTypeSlimSerializer

class PrivateLeaveTypeListSerializer(ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "uid",
            "name",
            "display_name",
            "definition",
            "color",
            "maximum_allocation",
            "allow_after_working_days",
            "max_consecutive_allowed",
            "maximum_allocation_hours",
            "leave_type",
            "is_carry_forward",
            "max_carry_forwarded",
            "carry_expiry_days",
            "is_encashable",
            "max_encashable",
            "min_encashable",
            "earning_components",
            "is_earned_leave",
            "earned_leave_frequency",
            "allocate_on_day",
            "rounders",
            "is_partially_paid",
            "fraction_salary_per_leave",
            "is_leave_without_pay",
            "allow_negative_balance",
            "include_holidays_within_leave",
            "is_optional_leave",
            "allow_over_allocation",
            "is_compensatory",
            "created_by",
            "is_active",
            "status"
        ]
        read_only_fields = ["uid", "created_by"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)

class PrivateLeaveTypeDetailsSerializer(ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "uid",
            "name",
            "display_name",
            "definition",
            "color",
            "maximum_allocation",
            "allow_after_working_days",
            "max_consecutive_allowed",
            "maximum_allocation_hours",
            "leave_type",
            "is_carry_forward",
            "max_carry_forwarded",
            "carry_expiry_days",
            "is_encashable",
            "max_encashable",
            "min_encashable",
            "earning_components",
            "is_earned_leave",
            "earned_leave_frequency",
            "allocate_on_day",
            "rounders",
            "is_partially_paid",
            "fraction_salary_per_leave",
            "is_leave_without_pay",
            "allow_negative_balance",
            "include_holidays_within_leave",
            "is_optional_leave",
            "allow_over_allocation",
            "is_compensatory",
            "created_by",
            "is_active",
            "status"
        ]
        read_only_fields = ["uid", "created_by"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)