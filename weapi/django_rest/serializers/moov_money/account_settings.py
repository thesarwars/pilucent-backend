from rest_framework import serializers
from moovmoneyio.models import MoovAccountSettings, MoovBankAccountSettings

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)


class MoovAccountCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MoovAccountSettings
        fields = [
            "moov_account_uid",
            "moov_account_display_name",
            "moov_representative_uid",
            "status",
            "company",
            "created_by",
        ]
        # company and created_by are populated from request in create()
        read_only_fields = ["slug", "status", "company", "created_by"]

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        return super().create(validated_data)


class MoovBankAccountSettingsSerializer(serializers.ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    class Meta:
        model = MoovBankAccountSettings
        fields = [
            "uid",
            "bank_account_uid",
            "account_type",
            "account_number",
            "routing_number",
            "account_holder_name",
            "account_holder_type",
            "bank_name",
            "status",
            "bank_account_kind",
            "created_at",
            "employee",
        ]


class MoovAccountDetailSerializer(serializers.ModelSerializer):
    moov_bank_accounts = MoovBankAccountSettingsSerializer(many=True, read_only=True)
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = MoovAccountSettings
        fields = [
            "uid",
            "moov_account_uid",
            "moov_account_display_name",
            "moov_representative_uid",
            "status",
            "moov_bank_accounts",
            "created_by",
            "created_at",
            "updated_at",
        ]
