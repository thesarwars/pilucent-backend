"""Slim nested representations of a BD employee, for other apps' payloads.

Nested inside those apps' snake_case responses, so these stay snake_case; the
BD employee API itself (weapi.django_rest.serializers.bd_employees) is camelCase.
"""

from rest_framework.serializers import ModelSerializer

from employeeio.models import Employee

SLIM_FIELDS = ["code", "name_en", "name_bn", "photo", "created_at", "updated_at"]


class PrivateCompanyEmployeeSlimSerializer(ModelSerializer):
    class Meta:
        model = Employee
        fields = ["uid"] + SLIM_FIELDS
        read_only_fields = fields


class PublicCompanyEmployeeSlimSerializer(ModelSerializer):
    class Meta:
        model = Employee
        fields = SLIM_FIELDS
        read_only_fields = fields
