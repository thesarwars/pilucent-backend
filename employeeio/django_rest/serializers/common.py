from versatileimagefield.serializers import VersatileImageFieldSerializer

from rest_framework.serializers import ModelSerializer
from rest_framework import serializers

from ...models import (
    Employee,
    EmployeeSalary,
    EmployeeBankingInformation,
    EmployeeGarnishment,
)


class CompanyEmployeeBaseSerializer(ModelSerializer):
    class Meta:
        model = Employee
        fields = ["full_name", "employee_id", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateCompanyEmployeeSlimSerializer(CompanyEmployeeBaseSerializer):
    image = VersatileImageFieldSerializer(
        sizes=[
            ("original", "url"),
            ("at350x350", "crop__350x350"),
        ],
        source="get_image",
    )

    class Meta:
        model = CompanyEmployeeBaseSerializer.Meta.model
        fields = ["uid", "image"] + CompanyEmployeeBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCompanyEmployeeSlimSerializer(CompanyEmployeeBaseSerializer):

    class Meta:
        model = CompanyEmployeeBaseSerializer.Meta.model
        fields = ["slug"] + CompanyEmployeeBaseSerializer.Meta.fields
        read_only_fields = fields


class EmployeeSalaryBaseSerializer(ModelSerializer):
    class Meta:
        model = EmployeeSalary
        fields = ["total", "over_time_rate", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateEmployeeSalarySlimSerializer(EmployeeSalaryBaseSerializer):

    class Meta:
        model = EmployeeSalaryBaseSerializer.Meta.model
        fields = [
            "uid",
        ] + EmployeeSalaryBaseSerializer.Meta.fields
        read_only_fields = fields


class PrivateWeEmployeeGarnishmentSlimSerializer(ModelSerializer):

    class Meta:
        model = EmployeeGarnishment
        fields = [
            "uid",
            "title",
            "status",
            "kind",
            "description",
            "total_requsted_amount",
            "total_maximum_percentage_of_disposal_income",
            "created_at",
        ]
        read_only_fields = fields


class PublicEmployeeSalarySlimSerializer(EmployeeSalaryBaseSerializer):

    class Meta:
        model = EmployeeSalaryBaseSerializer.Meta.model
        fields = [
            "slug",
        ] + EmployeeSalaryBaseSerializer.Meta.fields
        read_only_fields = fields


class CompanyEmployeeBaseSerializer(ModelSerializer):
    class Meta:
        model = Employee
        fields = ["full_name", "code", "created_at", "updated_at"]
        read_only_fields = fields


class EmployeeBankingInformationBaseSerializer(CompanyEmployeeBaseSerializer):

    class Meta:
        model = EmployeeBankingInformation
        fields = [
            "uid",
            "status",
            "kind",
            "bank_name",
            "bank_account_number",
            "bank_account_type",
            "routing_number",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateEmployeeBankingInformationSlimSerializer(
    EmployeeBankingInformationBaseSerializer
):

    class Meta:
        model = EmployeeBankingInformationBaseSerializer.Meta.model
        fields = ["uid"] + EmployeeBankingInformationBaseSerializer.Meta.fields
        read_only_fields = fields


class PrivateEmployeeUserSerializer(ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    middle_name = serializers.CharField(source="user.middle_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "uid",
            "email",
            "first_name",
            "middle_name",
            "last_name",
        ]
        read_only_fields = fields
