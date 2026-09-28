from rest_framework import serializers


class PrivateWeInventoryValuationDetailRowSerializer(serializers.Serializer):
    """One transaction row on the Inventory Valuation Detail report.

    ``quantity`` is signed (+ in / - out); ``inventory_cost`` is the signed value
    moved (FIFO COGS on outbound); ``running_quantity`` / ``running_value`` are
    the balances after the line. The report is assembled in the view, so this
    documents the per-row contract rather than mapping a single model.
    """

    uid = serializers.CharField(read_only=True)
    date = serializers.CharField(read_only=True)
    transaction_type = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    quantity = serializers.FloatField(read_only=True)
    rate = serializers.FloatField(read_only=True, allow_null=True)
    inventory_cost = serializers.FloatField(read_only=True)
    running_quantity = serializers.FloatField(read_only=True)
    running_value = serializers.FloatField(read_only=True)
