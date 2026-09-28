from rest_framework import serializers


class PrivateWeApAgingDetailRowSerializer(serializers.Serializer):
    """One transaction line on the A/P Aging Detail report.

    The report is composite (open bills + unapplied vendor credits) and is
    assembled into aging bands in the view, so this serializer documents the
    per-row contract rather than mapping a single model.
    """

    uid = serializers.CharField(read_only=True)
    kind = serializers.CharField(read_only=True)  # BILL | VENDOR_CREDIT
    date = serializers.DateField(read_only=True)
    transaction_type = serializers.CharField(read_only=True)  # Bill | Vendor Credit
    num = serializers.CharField(read_only=True, allow_blank=True)
    vendor_display_name = serializers.CharField(read_only=True, allow_null=True)
    store_full_name = serializers.CharField(read_only=True, allow_blank=True)
    due_date = serializers.DateField(read_only=True, allow_null=True)
    past_due = serializers.IntegerField(read_only=True, allow_null=True)
    amount = serializers.FloatField(read_only=True)
    open_balance = serializers.FloatField(read_only=True)
