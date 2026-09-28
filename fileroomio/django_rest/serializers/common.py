from rest_framework.serializers import ModelSerializer, CharField, FileField

from fileroomio.models import FileItem, FileItemConnector


class FileItemBaseSerializer(ModelSerializer):
    class Meta:
        model = FileItem
        fields = ["title", "file", "status", "kind"]
        read_only_fields = fields


class PrivateFileItemSerializer(FileItemBaseSerializer):
    class Meta:
        model = FileItemBaseSerializer.Meta.model
        fields = ["uid"] + FileItemBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicFileItemSerializer(FileItemBaseSerializer):
    class Meta:
        model = FileItemBaseSerializer.Meta.model
        fields = ["slug"] + FileItemBaseSerializer.Meta.fields
        read_only_fields = fields


class FileItemConnectorBaseSerializer(ModelSerializer):
    title = CharField(source="file_item.title")
    file = FileField(source="file_item.file")
    status = CharField(source="file_item.status")
    kind = CharField(source="file_item.kind")

    class Meta:
        model = FileItemConnector
        fields = ["model_kind", "title", "file", "status", "kind"]
        read_only_fields = fields


class PrivateFileItemConnectorSerializer(FileItemConnectorBaseSerializer):
    class Meta:
        model = FileItemConnectorBaseSerializer.Meta.model
        fields = ["uid"] + FileItemConnectorBaseSerializer.Meta.fields
        read_only_fields = fields
