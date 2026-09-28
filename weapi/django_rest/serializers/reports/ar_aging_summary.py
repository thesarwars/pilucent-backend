from rest_framework import serializers


class PrivateWeArAgingSummaryRowSerializer(serializers.Serializer):
    """One customer row on the A/R Aging Summary report.

    ``buckets`` maps each aging bucket key (current / 1_30 / 31_60 / 61_90 /
    90_plus) to that customer's netted open balance in the bucket; ``total`` is
    the sum across the row. The report is assembled in the view, so this
    serializer documents the per-row contract rather than mapping a single model.
    """

    customer_uid = serializers.CharField(read_only=True, allow_null=True)
    customer_display_name = serializers.CharField(read_only=True)
    buckets = serializers.DictField(child=serializers.FloatField(), read_only=True)
    total = serializers.FloatField(read_only=True)
