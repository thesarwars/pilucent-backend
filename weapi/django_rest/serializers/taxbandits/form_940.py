from rest_framework import serializers
from taxbanditsio.models import TaxBanditsReturn940

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)


class TaxBanditsReturn940CreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxBanditsReturn940
        fields = [
            "tax_year",
            "record_id",
            "submission_id",
            "status",
            "pdf_url",
            "business_account",
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



