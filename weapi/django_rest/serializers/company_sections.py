from rest_framework import serializers

from rest_framework.serializers import ModelSerializer, ValidationError

from companyio.django_rest.serializers.common import (
    PrivateCompanyDepartmentSlimSerializer,
)
from companyio.models import CompanySection, CompanyDepartment


class PrivateWeCompanySectionListSerializer(ModelSerializer):
    department = PrivateCompanyDepartmentSlimSerializer(read_only=True)
    department_uid = serializers.SlugRelatedField(
        slug_field="uid", queryset=CompanyDepartment.objects.filter(), write_only=True
    )

    class Meta:
        model = CompanySection
        fields = ["uid", "title", "department", "department_uid"]
        read_only_fields = [
            "uid",
            "department",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        user = self.context["request"].user
        company = user.get_active_company()
        if CompanySection.objects.filter(title=attrs["title"], company=company):
            raise ValidationError({"message":"Section already exists."})

        attrs["department"] = attrs.pop("department_uid", None)
        attrs["company"] = company
        return super().validate(attrs)


class PrivateWeCompanySectionDetailsSerializer(ModelSerializer):
    department = PrivateCompanyDepartmentSlimSerializer(read_only=True)
    department_uid = serializers.SlugRelatedField(
        slug_field="uid", queryset=CompanyDepartment.objects.filter(), write_only=True
    )

    class Meta:
        model = CompanySection
        fields = ["uid", "title", "department", "department_uid"]
        read_only_fields = [
            "uid",
            "department",
            "created_at",
            "updated_at",
        ]

    def update(self, instance, validated_data):
        validated_data["department"] = validated_data.pop("department_uid", None)
        return super().update(instance, validated_data)
