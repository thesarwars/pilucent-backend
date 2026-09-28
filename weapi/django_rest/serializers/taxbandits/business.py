from rest_framework import serializers
from taxbanditsio.models import TaxBanditsBusinessAccount

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)


class TaxBanditsBusinessCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxBanditsBusinessAccount
        fields = [
            "payer_ref",
            "legal_name",
            "ein_or_ssn",
            "contact_name",
            "contact_phone",
            "email",
            "address1",
            "address2",
            "city",
            "state",
            "zip",
            "tb_business_id",
            "status",
            "company",
            "created_by",
        ]
        read_only_fields = ["uid", "company", "created_by"]

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        return super().create(validated_data)


class TaxBanditsBusinessUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxBanditsBusinessAccount
        fields = [
            "payer_ref",
            "legal_name",
            "ein_or_ssn",
            "contact_name",
            "contact_phone",
            "email",
            "address1",
            "address2",
            "city",
            "state",
            "zip",
            "tb_business_id",
            "status",
            "company",
            "created_by",
        ]
        read_only_fields = ["uid", "company", "created_by"]

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        return super().update(instance, validated_data)
