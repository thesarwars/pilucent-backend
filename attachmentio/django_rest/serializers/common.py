from rest_framework.serializers import ModelSerializer, CharField

from attachmentio.models import Attachment


class AttachmentBaseSerializer(ModelSerializer):
    image = CharField(source='image.url', read_only=True)

    class Meta:
        model = Attachment
        fields = [
            'image',
            'description',
        ]
        read_only_fields = fields


class PrivateAttachmentSerializer(AttachmentBaseSerializer):
    class Meta:
        model = AttachmentBaseSerializer.Meta.model
        fields = ['uid'] + AttachmentBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicAttachmentSerializer(AttachmentBaseSerializer):
    class Meta:
        model = AttachmentBaseSerializer.Meta.model
        fields = ['slug'] + AttachmentBaseSerializer.Meta.fields
        read_only_fields = fields
