from rest_framework import serializers


class PrivateWeSalesTaxLiabilityRowSerializer(serializers.Serializer):
    """One rate-component row on the Sales Tax Liability report.

    The report is assembled in the view into agency groups (each with these
    component rows + an agency total that sums Tax Amount only); this documents
    the per-component row contract.
    """

    name = serializers.CharField(read_only=True)  # rate component (e.g. California State)
    gross_total = serializers.FloatField(read_only=True)
    non_taxable = serializers.FloatField(read_only=True)
    taxable_amount = serializers.FloatField(read_only=True)
    tax_amount = serializers.FloatField(read_only=True)
