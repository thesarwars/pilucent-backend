"""Serializers for statutory PayrollTaxConfig reference data.

Reads are assembled by helpers.tax_config (not a ModelSerializer); these cover
the list-metadata view and admin writes.
"""

from rest_framework import serializers

from payrollio.django_rest.helpers.tax_config import normalize_jurisdiction
from payrollio.models import PayrollTaxConfig


class PayrollTaxConfigMetaSerializer(serializers.ModelSerializer):
    """Row metadata for the list view (no heavy ``data`` payload)."""

    class Meta:
        model = PayrollTaxConfig
        fields = [
            "uid",
            "year",
            "jurisdiction",
            "status",
            "version",
            "effective_from",
            "effective_to",
            "source_notes",
            "updated_at",
        ]
        read_only_fields = fields


class PayrollTaxConfigWriteSerializer(serializers.Serializer):
    """Admin upsert of one ``(year, jurisdiction)`` document."""

    data = serializers.JSONField()
    source_notes = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    effective_from = serializers.DateField(required=False, allow_null=True)
    effective_to = serializers.DateField(required=False, allow_null=True)

    def validate_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("data must be a JSON object.")
        return value

    def validate(self, attrs):
        jurisdiction = normalize_jurisdiction(self.context.get("jurisdiction"))
        if not jurisdiction:
            raise serializers.ValidationError(
                {"jurisdiction": "Must be FEDERAL or a valid US state code."}
            )
        attrs["jurisdiction"] = jurisdiction
        return attrs
