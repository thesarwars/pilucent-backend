"""Serializers for the Economic Nexus dashboard/detail (Phase 1).

The payload is assembled in the views (status row + the state's in-force rule), so
these document the row contract rather than mapping a single model.
"""

from rest_framework import serializers

from nexusio.choices import NexusFilingFrequencyChoices
from nexusio.models import NexusAlertLog, NexusSettings


class PrivateWeNexusStateRowSerializer(serializers.Serializer):
    state_code = serializers.CharField(read_only=True)
    state_name = serializers.CharField(read_only=True)
    has_sales_tax = serializers.BooleanField(read_only=True)
    # rule
    sales_threshold = serializers.FloatField(read_only=True, allow_null=True)
    txn_threshold = serializers.IntegerField(read_only=True, allow_null=True)
    combination_logic = serializers.CharField(read_only=True)
    includable_sales_basis = serializers.CharField(read_only=True)
    measurement_period_type = serializers.CharField(read_only=True)
    # measured activity + verdict
    window_start = serializers.DateField(read_only=True, allow_null=True)
    window_end = serializers.DateField(read_only=True, allow_null=True)
    sales_amount = serializers.FloatField(read_only=True)
    taxable_sales_amount = serializers.FloatField(read_only=True)
    txn_count = serializers.IntegerField(read_only=True)
    pct_of_sales_threshold = serializers.FloatField(read_only=True, allow_null=True)
    pct_of_txn_threshold = serializers.FloatField(read_only=True, allow_null=True)
    threshold_met = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    threshold_met_date = serializers.DateField(read_only=True, allow_null=True)
    last_evaluated_at = serializers.DateTimeField(read_only=True, allow_null=True)


class PrivateWeNexusRecalculateSerializer(serializers.Serializer):
    detail = serializers.CharField(read_only=True)
    evaluated_states = serializers.IntegerField(read_only=True)
    unattributed_sales = serializers.FloatField(read_only=True)


class PrivateWeNexusRegistrationInputSerializer(serializers.Serializer):
    """Body for mark-nexus / start-agency-setup (all optional)."""

    collection_start_date = serializers.DateField(required=False, allow_null=True)
    filing_frequency = serializers.ChoiceField(
        choices=NexusFilingFrequencyChoices.choices, required=False, allow_null=True
    )
    sales_tax_permit_number = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    mark_registered = serializers.BooleanField(required=False, default=False)


class PrivateWeNexusAlertSerializer(serializers.ModelSerializer):
    acknowledged = serializers.SerializerMethodField()

    class Meta:
        model = NexusAlertLog
        fields = [
            "uid",
            "state_code",
            "alert_type",
            "threshold_pct_at_alert",
            "triggered_at",
            "acknowledged",
            "acknowledged_at",
        ]
        read_only_fields = fields

    def get_acknowledged(self, obj):
        return obj.acknowledged_at is not None


class PrivateWeNexusSettingsSerializer(serializers.ModelSerializer):
    # Only the settings that actually affect P1/P2 behaviour are exposed.
    # `include_marketplace_in_measurement` (no channel data yet) and
    # `alert_channels` (P3) stay on the model as reserved, not yet wired.
    class Meta:
        model = NexusSettings
        fields = ["warning_fraction"]
