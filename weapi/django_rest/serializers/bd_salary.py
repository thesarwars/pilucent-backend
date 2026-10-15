"""Request bodies for the salary profile API (docs/backend/salary-profile.md §6)."""

from decimal import Decimal

from rest_framework import serializers

from employeeio.choices import (
    ArrearsRunChoices,
    OverrideBasisChoices,
    RevisionMethodChoices,
    RevisionTypeChoices,
    SalaryTemplateChoices,
)

from .bd_employees import MoneyField, StrictSerializer

# Methods the revise drawer offers; an override has its own endpoint.
WRITE_METHODS = [(v, label) for v, label in RevisionMethodChoices.choices if v != RevisionMethodChoices.OVERRIDE]
CURRENT_TEMPLATES = [(v, label) for v, label in SalaryTemplateChoices.choices
                     if v not in (SalaryTemplateChoices.STD, SalaryTemplateChoices.CLASSIC)]


class SalaryStructureWriteSerializer(StrictSerializer):
    """Assign, reassign or revise (§6.1). Either a template and an amount
    (assign / reassign), or a revision method and its value."""

    decimal_keys = ("gross", "value")

    templateCode = serializers.ChoiceField(CURRENT_TEMPLATES, required=False, allow_null=True)
    # Gross on a gross-down template; basic on RMG (optional there: the
    # grade's gazetted basic).
    gross = MoneyField(required=False, allow_null=True)
    method = serializers.ChoiceField(WRITE_METHODS, required=False, allow_null=True)
    # A percentage or an amount, as a decimal string.
    value = serializers.CharField(required=False, allow_null=True, allow_blank=False)
    effectiveFrom = serializers.DateField(required=False, allow_null=True)
    revisionType = serializers.ChoiceField(RevisionTypeChoices.choices, required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    rounding = serializers.IntegerField(required=False, default=0)
    arrearsRun = serializers.ChoiceField(ArrearsRunChoices.choices, required=False, allow_null=True)
    # The uid of the structure this change is based on (optimistic concurrency, §8.1).
    expectedStructure = serializers.UUIDField(required=False, allow_null=True)
    idempotencyKey = serializers.CharField(required=False, allow_blank=True, max_length=80)
    preview = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("method") and not attrs.get("templateCode"):
            raise serializers.ValidationError({"templateCode": ["Name a template, or a revision method."]})
        value = attrs.get("value")
        if value is not None:
            try:
                finite = Decimal(str(value)).is_finite()
            except Exception:
                finite = False
            if not finite:
                raise serializers.ValidationError({"value": ["Send the value as a decimal string."]})
        attrs["reason"] = attrs.get("reason") or ""
        return attrs


class OverrideRowSerializer(serializers.Serializer):
    code = serializers.ChoiceField(["BASIC", "HRA", "MED", "CONV", "OTHER"])
    basis = serializers.ChoiceField(OverrideBasisChoices.choices)
    value = serializers.CharField()

    def validate_value(self, value):
        try:
            if not Decimal(str(value)).is_finite():
                raise ValueError
        except Exception:
            raise serializers.ValidationError("Send a decimal string.") from None
        return value


class SalaryOverrideSerializer(StrictSerializer):
    rows = OverrideRowSerializer(many=True)
    # REBALANCE keeps gross and lets Other allowance absorb the difference;
    # CHANGE lets gross become the sum of the lines.
    mode = serializers.ChoiceField(["REBALANCE", "CHANGE"], required=False, default="REBALANCE")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    effectiveFrom = serializers.DateField(required=False, allow_null=True)
    arrearsRun = serializers.ChoiceField(ArrearsRunChoices.choices, required=False, allow_null=True)
    idempotencyKey = serializers.CharField(required=False, allow_blank=True, max_length=80)
    preview = serializers.BooleanField(required=False, default=False)


class SalaryCancelSerializer(StrictSerializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
