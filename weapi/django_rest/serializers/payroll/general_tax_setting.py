from rest_framework import serializers
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from payrollio.models import PayrollGeneralTaxSetting
from payrollio.django_rest.helpers.tax_ein_sync import sync_company_federal_ein


class PrivateWePayrollGeneralTaxSettingListCreateSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = PayrollGeneralTaxSetting
        fields = [
            "uid",
            "title",
            "address",
            "city",
            "state",
            "zip_code",
            "company_type",
            "ein_number",
            "created_by",
        ]
        read_only_fields = ["uid", "created_by"]

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        company = user.get_active_company()
        if PayrollGeneralTaxSetting.objects.filter(company=company).exists():
            raise serializers.ValidationError(
                {
                    "detail": (
                        "General tax setting already exists for this company. "
                        "Update the existing record instead."
                    )
                }
            )
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = company
        instance = super().create(validated_data)
        if "ein_number" in validated_data:
            sync_company_federal_ein(company, instance.ein_number)
        return instance


class PrivateWePayrollGeneralTaxSettingDetailUpdateSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = PayrollGeneralTaxSetting
        fields = [
            "uid",
            "title",
            "address",
            "city",
            "state",
            "zip_code",
            "company_type",
            "ein_number",
            "created_by",
        ]
        read_only_fields = ["uid", "created_by"]
        
    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        company = user.get_active_company()
        validated_data["company"] = company
        instance = super().update(instance, validated_data)
        if "ein_number" in validated_data:
            sync_company_federal_ein(company, instance.ein_number)
        return instance