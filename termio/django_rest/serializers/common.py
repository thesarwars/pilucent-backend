from rest_framework.serializers import ModelSerializer

from termio.models import Term


class TermBaseSerializer(ModelSerializer):
    class Meta:
        model = Term
        fields = ["title", "days", "is_active", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateTermSlimSerializer(TermBaseSerializer):
    class Meta:
        model = TermBaseSerializer.Meta.model
        fields = ["uid"] + TermBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicTermSlimSerializer(TermBaseSerializer):
    class Meta:
        model = TermBaseSerializer.Meta.model
        fields = ["slug"] + TermBaseSerializer.Meta.fields
        read_only_fields = fields
