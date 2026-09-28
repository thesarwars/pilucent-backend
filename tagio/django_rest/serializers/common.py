from rest_framework.serializers import ModelSerializer, CharField

from tagio.models import Tag


class TagBaseSerializer(ModelSerializer):
    class Meta:
        model = Tag
        fields = ["title", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateTagSlimSerializer(TagBaseSerializer):
    class Meta:
        model = TagBaseSerializer.Meta.model
        fields = ["uid"] + TagBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicTagSlimSerializer(TagBaseSerializer):
    class Meta:
        model = TagBaseSerializer.Meta.model
        fields = ["slug"] + TagBaseSerializer.Meta.fields
        read_only_fields = fields
