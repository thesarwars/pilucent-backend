from rest_framework import serializers


class PrivateWeArAgingDetailRowSerializer(serializers.Serializer):
    """One transaction line on the A/R Aging Detail report.

    The report is composite (open invoices + unapplied credit memos) and is
    assembled into aging bands in the view, so this serializer documents the
    per-row contract rather than mapping a single model.
    """

    uid = serializers.CharField(read_only=True)
    kind = serializers.CharField(read_only=True)  # INVOICE | CREDIT_MEMO
    date = serializers.DateField(read_only=True)
    transaction_type = serializers.CharField(read_only=True)  # Invoice | Credit Memo
    num = serializers.CharField(read_only=True, allow_blank=True)
    customer_display_name = serializers.CharField(read_only=True, allow_null=True)
    store_full_name = serializers.CharField(read_only=True, allow_blank=True)
    due_date = serializers.DateField(read_only=True, allow_null=True)
    past_due = serializers.IntegerField(read_only=True, allow_null=True)
    amount = serializers.FloatField(read_only=True)
    open_balance = serializers.FloatField(read_only=True)
