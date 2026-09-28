from rest_framework import serializers


class PrivateWeNexusExposureRowSerializer(serializers.Serializer):
    state_code = serializers.CharField(read_only=True)
    state_name = serializers.CharField(read_only=True, allow_null=True)
    window_start = serializers.CharField(read_only=True, allow_null=True)
    window_end = serializers.CharField(read_only=True, allow_null=True)
    sales_amount = serializers.FloatField(read_only=True)
    sales_threshold = serializers.FloatField(read_only=True, allow_null=True)
    pct_of_sales_threshold = serializers.FloatField(read_only=True, allow_null=True)
    txn_count = serializers.IntegerField(read_only=True)
    txn_threshold = serializers.IntegerField(read_only=True, allow_null=True)
    pct_of_txn_threshold = serializers.FloatField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    threshold_met_date = serializers.CharField(read_only=True, allow_null=True)
    registration_status = serializers.CharField(read_only=True)


class PrivateWeNexusThresholdHistoryRowSerializer(serializers.Serializer):
    state_code = serializers.CharField(read_only=True)
    state_name = serializers.CharField(read_only=True, allow_null=True)
    alert_type = serializers.CharField(read_only=True)
    threshold_pct_at_alert = serializers.FloatField(read_only=True, allow_null=True)
    triggered_at = serializers.CharField(read_only=True, allow_null=True)
    acknowledged_at = serializers.CharField(read_only=True, allow_null=True)
