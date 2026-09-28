from rest_framework import serializers

from payrollio.models import PayrollGeneralTaxSetting, PayrollWorkLocation
from payrollio.django_rest.helpers.accounting_preferences_setup import normalize_us_state
from employeeio.models import Employee
from employeeio.django_rest.serializers.common import PublicCompanyEmployeeSlimSerializer


def _apply_general_tax_setting_address_defaults(company, attrs):
    # Store the 2-letter code so downstream tax group keys are synthesized
    # correctly; keep the raw value only if it isn't a recognizable state.
    if attrs.get("location_state"):
        attrs["location_state"] = (
            normalize_us_state(attrs["location_state"]) or attrs["location_state"]
        )

    general_tax_setting = PayrollGeneralTaxSetting.objects.filter(
        company=company
    ).first()
    if not general_tax_setting:
        return attrs

    if not attrs.get("location_state") and general_tax_setting.state:
        attrs["location_state"] = (
            normalize_us_state(general_tax_setting.state) or general_tax_setting.state
        )
    if not attrs.get("location_address") and general_tax_setting.address:
        attrs["location_address"] = general_tax_setting.address
    if not attrs.get("location_city") and general_tax_setting.city:
        attrs["location_city"] = general_tax_setting.city
    if not attrs.get("location_zip") and general_tax_setting.zip_code:
        attrs["location_zip"] = general_tax_setting.zip_code
    return attrs


class PayrollWorkLocationSlimSerializer(serializers.ModelSerializer):
    total_employees = serializers.SerializerMethodField()

    class Meta:
        model = PayrollWorkLocation
        fields = [
            "uid",
            "status",
            "is_primary",
            "location_address",
            "location_city",
            "location_state",
            "location_zip",
            "total_employees",
        ]
        read_only_fields = ["uid", "created_by", "is_primary"]

    def get_total_employees(self, obj):
        return Employee.objects.filter(work_locations=obj).count()

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        attrs = _apply_general_tax_setting_address_defaults(company, attrs)
        attrs["company"] = company
        attrs["created_by"] = self.context["request"].user.get_employee()
        attrs["is_primary"] = False
        return super().validate(attrs)


class PayrollWorkLocationDetailsSerializer(serializers.ModelSerializer):
    employees = serializers.SerializerMethodField()
    total_employees = serializers.SerializerMethodField()

    class Meta:
        model = PayrollWorkLocation
        fields = [
            "uid",
            "status",
            "is_primary",
            "location_address",
            "location_city",
            "location_state",
            "location_zip",
            "total_employees",
            "employees",
        ]
        read_only_fields = ["uid", "created_by", "is_primary"]

    def get_total_employees(self, obj):
        return Employee.objects.filter(work_locations=obj).count()

    def get_employees(self, obj):
        employees = Employee.objects.filter(work_locations=obj)
        return PublicCompanyEmployeeSlimSerializer(employees, many=True).data

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        attrs = _apply_general_tax_setting_address_defaults(company, attrs)
        attrs["company"] = company
        attrs["created_by"] = self.context["request"].user.get_employee()
        if self.instance is None:
            attrs["is_primary"] = False
        return super().validate(attrs)
