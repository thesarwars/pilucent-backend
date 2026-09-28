from rest_framework.serializers import ModelSerializer

from ...models import CreditNote


class CreditNoteBaseSerializer(ModelSerializer):
    class Meta:
        model = CreditNote
        fields = [
            "uid",
            "credit_note_number",
            "kind",
            "status",
            "tax_kind",
            "total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PrivateCreditNoteSlimSerializer(CreditNoteBaseSerializer):
    class Meta:
        model = CreditNoteBaseSerializer.Meta.model
        fields = ["uid"] + CreditNoteBaseSerializer.Meta.fields


class PublicCreditNoteSlimSerializer(CreditNoteBaseSerializer):
    class Meta:
        model = CreditNoteBaseSerializer.Meta.model
        fields = ["slug"] + CreditNoteBaseSerializer.Meta.fields
