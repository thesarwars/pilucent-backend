from rest_framework.serializers import ModelSerializer, SlugRelatedField

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from companyio.django_rest.serializers.common import (
    PrivateCompanyDesignationSlimSerializer,
    PrivateCompanyDepartmentSlimSerializer,
)

from payrollio.models import SalaryAdjustment
from employeeio.models import Employee


class PrivateWeSalaryAdjustmentListSerializer(ModelSerializer):

    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all(),
        write_only=True,
        required=False,
        # source="employee",
    )
    designation = PrivateCompanyDesignationSlimSerializer(
        source="employee.designation", read_only=True
    )
    department = PrivateCompanyDepartmentSlimSerializer(
        source="employee.department", read_only=True
    )

    class Meta:
        model = SalaryAdjustment
        fields = [
            "uid",
            # "slug",
            "title",
            "status",
            "kind",
            "join_date",
            "input_date",
            "amount",
            "employee",
            "employee_uid",
            "designation",
            "department",
            "remark",
            # "created_at",
            # "updated_at",
        ]
        read_only_fields = [
            "uid",
            "slug",
            "employee",
            "designation",
            "department",
            "created_at",
            "updated_at",
        ]

    # def validate(self, attrs):
    #     return super().validate(attrs)

    def create(self, validated_data):
        validated_data["employee"] = validated_data.pop('employee_uid')
        return super().create(validated_data)
