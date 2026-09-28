from rest_framework.serializers import ModelSerializer

from ...models import TransactionSession


class TransactionSessionBaseSerializer(ModelSerializer):
    class Meta:
        model = TransactionSession
        fields = [
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TransactionSessionSerializer(TransactionSessionBaseSerializer):
    class Meta:
        model = TransactionSessionBaseSerializer.Meta.model
        fields = ["uid"] + TransactionSessionBaseSerializer.Meta.fields
        read_only_fields = fields


class TransactionSessionSerializer(TransactionSessionBaseSerializer):
    class Meta:
        model = TransactionSessionBaseSerializer.Meta.model
        fields = ["slug"] + TransactionSessionBaseSerializer.Meta.fields
        read_only_fields = fields
