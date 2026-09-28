from payrollio.models import PayrollContactInfoSetting
from rest_framework import serializers
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

class PayrollContactInfoSettingSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    
    class Meta:
        model = PayrollContactInfoSetting
        fields = [
            "uid",
            "contact_first_name",
            "contact_last_name",
            "contact_email",
            "contact_phone",
            "created_by",
        ]
        read_only_fields = ["uid", "created_by"]
    
    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        attrs["created_by"] = self.context["request"].user.get_employee()
        return super().validate(attrs)

        
class PayrollContactInfoSettingSerializerDetailUpdateSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = PayrollContactInfoSetting
        fields = [
            "uid",
            "contact_first_name",
            "contact_last_name",
            "contact_email",
            "contact_phone",
            "created_by",
        ]
        read_only_fields = ["uid", "created_by"]

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        return super().update(instance, validated_data)