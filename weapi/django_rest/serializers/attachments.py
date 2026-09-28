import os

from rest_framework.serializers import ModelSerializer, ValidationError

from common.django_rest.helpers.decorators import set_auditlog_actor

from fileroomio.choices import FileItemConnectorModelKindChoices, FileItemStatusChoices
from fileroomio.models import FileItem

from fileroomio.django_rest.helpers.file_helpers import get_file_kind
from fileroomio.django_rest.services.files import FileService


class PrivateWeAttachmentListSerializer(ModelSerializer):
    class Meta:
        model = FileItem
        fields = [
            "uid",
            "title",
            "file",
            "description",
            "status",
            "kind",
            "link",
            "is_report",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "title",
            "link",
            "is_report",
            "description",
            "status",
            "kind",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        company = self.context["request"].user.get_active_company()
        file = validated_data["file"]
        title = file.name

        # FileItem
        # if FileItem.objects.filter(title=title, company=company):
        #     raise ValidationError("File with this name already exists.")
        validated_data["company"] = company
        validated_data["title"] = title
        return super().validate(validated_data)

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["status"] = FileItemStatusChoices.PUBLISHED
        validated_data["kind"] = get_file_kind(
            os.path.splitext(validated_data["title"])[1]
        )
        return super().create(validated_data)


class PrivateWeAttachmentDetailsSerializer(ModelSerializer):

    class Meta:
        model = FileItem
        fields = [
            "uid",
            "title",
            "file",
            "description",
            "status",
            "kind",
            "link",
            "is_report",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "title",
            "image",
            "link",
            "description",
            "status",
            "kind",
            "is_report",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        if not validated_data["file"]:
            raise ValidationError("File is required")
        return super().validate(validated_data)

    @set_auditlog_actor
    def update(self, instance, validated_data):
        if file := validated_data["file"]:
            validated_data["title"] = file.name
            validated_data["kind"] = get_file_kind(os.path.splitext(file.name)[1])
        return super().update(instance, validated_data)
