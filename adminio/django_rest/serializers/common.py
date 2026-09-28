from rest_framework.serializers import ModelSerializer, CharField

from adminio.models import CompanyRole


class CompanyRoleBaseSerializer(ModelSerializer):
    class Meta:
        model = CompanyRole
        fields = ["name", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateCompanyRoleSlimSerializer(CompanyRoleBaseSerializer):
    class Meta:
        model = CompanyRoleBaseSerializer.Meta.model
        fields = ["uid"] + CompanyRoleBaseSerializer.Meta.fields
        read_only_fields = fields
