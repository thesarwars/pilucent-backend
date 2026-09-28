from rest_framework import serializers


class PrivateWeInventoryValuationSummaryRowSerializer(serializers.Serializer):
    """One inventory item row on the Inventory Valuation Summary report.

    ``asset_value`` is the cost value of the on-hand units; ``calc_avg`` is
    ``asset_value / quantity`` (the average unit cost). The report is assembled
    in the view, so this documents the per-row contract rather than mapping a
    single model.
    """

    uid = serializers.CharField(read_only=True)
    product = serializers.CharField(read_only=True, allow_null=True)
    sku = serializers.CharField(read_only=True, allow_blank=True)
    quantity = serializers.FloatField(read_only=True)
    asset_value = serializers.FloatField(read_only=True)
    calc_avg = serializers.FloatField(read_only=True)
