from rest_framework import serializers


class PrivateWeTaxableSalesItemSerializer(serializers.Serializer):
    """One product/service row on the Taxable Sales Summary.

    The report is assembled in the view into a no-item bucket + uncategorized
    item rows + category groups + a grand total; this documents the per-item
    row contract. ``uid`` is null for the no-item bucket; ``amount`` is the net
    taxable base (can be negative from credits/refunds/discounts).
    """

    uid = serializers.CharField(read_only=True, allow_null=True)
    label = serializers.CharField(read_only=True, allow_blank=True)
    amount = serializers.FloatField(read_only=True)
