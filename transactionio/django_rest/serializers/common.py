from rest_framework.serializers import ModelSerializer

from transactionio.models import TransactionMethod, TransactionInformation

class TransactionMethodBaseSerializer(ModelSerializer):
    class Meta:
        model = TransactionMethod
        fields = ["status", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateTransactionMethodSlimSerializer(TransactionMethodBaseSerializer):
    class Meta:
        model = TransactionMethodBaseSerializer.Meta.model
        fields = ["uid"] + TransactionMethodBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicTransactionMethodSlimSerializer(TransactionMethodBaseSerializer):
    class Meta:
        model = TransactionMethodBaseSerializer.Meta.model
        fields = ["slug"] + TransactionMethodBaseSerializer.Meta.fields
        read_only_fields = fields
        

class PrivateTransactionInformationSlimSerializer(ModelSerializer):
    class Meta:
        model = TransactionInformation
        fields = [
            "slug",
            "uid",
            "date",
            "description",
            "received",
            "spent",
            "payee",
            "category",
            "check_number",
            "is_matched",
        ]