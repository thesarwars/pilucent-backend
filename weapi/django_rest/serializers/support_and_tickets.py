import os

from rest_framework.serializers import (
    ModelSerializer,
    CharField,
    FileField,
    ListField,
    ValidationError,
    SerializerMethodField,
)

from django.db import transaction

from accounts.django_rest.serializers.common import PriateUserSlimSerializer

from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.decorators import set_auditlog_actor

from fileroomio.choices import FileItemConnectorModelKindChoices, FileItemStatusChoices
from fileroomio.django_rest.serializers.common import PrivateFileItemSerializer
from fileroomio.models import FileItem, FileItemConnector

from messageio.choices import InboxKindChoices, InboxStatusChoices
from messageio.models import Thread, Inbox

from rest_framework.generics import get_object_or_404

from fileroomio.django_rest.helpers.file_helpers import get_file_kind

from ...django_rest.helpers.inbox_helpers import get_inbox_target, get_inbox_is_seen


class PrivateWeSupportTicketListSerializer(ModelSerializer):
    content = CharField(write_only=True)
    is_seen = SerializerMethodField()
    user = SerializerMethodField()
    target = SerializerMethodField()

    class Meta:
        model = Inbox
        fields = [
            "uid",
            "title",
            "content",
            "ticket_noumber",
            "status",
            "kind",
            "is_seen",
            "user",
            "target",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "ticket_noumber",
            "status",
            "kind",
            "is_seen",
            "user",
            "target",
            "created_at",
            "updated_at",
        ]

    def get_is_seen(self, instance):
        return (
            None
            if isinstance(instance, dict)
            else get_inbox_is_seen(instance, self.context["request"].user)
        )

    def get_user(self, instance):
        return PriateUserSlimSerializer(self.context["request"].user).data

    def get_target(self, instance):
        target = (
            None
            if isinstance(instance, dict)
            else get_inbox_target(instance, self.context["request"].user)
        )
        return PriateUserSlimSerializer(target).data if target else None

    def validate(self, validated_data):
        user = self.context["request"].user
        if user.is_superuser == True:
            raise ValidationError({"message": "Admin can't create support ticket."})
        validated_data["user"] = user
        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = validated_data["user"]
        # Creating inbox
        inbox = Inbox.objects.create(
            title=validated_data["title"],
            user=user,
            kind=InboxKindChoices.SUPPORT_AND_TICKET,
            ticket_noumber=get_unique_id(Inbox, user.id, "ticket_noumber", "ST"),
        )
        # Creating thread
        Thread.objects.create(
            title=validated_data["title"],
            content=validated_data["content"],
            author=user,
            inbox=inbox,
        )
        return validated_data


class PrivateWeSupportTicketDetailsSerializer(ModelSerializer):
    is_seen = SerializerMethodField()
    user = SerializerMethodField()
    target = SerializerMethodField()

    class Meta:
        model = Inbox
        fields = [
            "uid",
            "title",
            "ticket_noumber",
            "status",
            "kind",
            "is_seen",
            "user",
            "target",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "title",
            "ticket_noumber",
            "kind",
            "is_seen",
            "user",
            "target",
            "created_at",
            "updated_at",
        ]

    def get_is_seen(self, instance):
        return get_inbox_is_seen(instance, self.context["request"].user)

    def get_user(self, instance):
        return PriateUserSlimSerializer(self.context["request"].user).data

    def get_target(self, instance):
        target = get_inbox_target(instance, self.context["request"].user)
        return (
            None
            if isinstance(instance, dict)
            else (PriateUserSlimSerializer(target).data if target else None)
        )

    def validate(self, validated_data):
        user = self.context["request"].user
        if not user.is_superuser:
            raise ValidationError(
                {"message": "You don't have permission to update the status!"}
            )

        if validated_data.get("status") not in [
            InboxStatusChoices.CLOSED,
            InboxStatusChoices.REMOVED,
            InboxStatusChoices.COMPLETED,
        ]:
            raise ValidationError(
                {"message": "You don't have permission to update the status!"}
            )
        return super().validate(validated_data)


class PrivateWeSupportTicketThreadListSerializer(ModelSerializer):
    author = PriateUserSlimSerializer(read_only=True)
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_items = PrivateFileItemSerializer(
        source="get_file_items", read_only=True, many=True
    )

    class Meta:
        model = Thread
        fields = [
            "uid",
            "kind",
            "author",
            "content",
            "files",
            "file_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "kind", "file_items", "created_at", "updated_at"]

    def validate(self, validated_data):
        # Scoped to the requester, matching the detail view. This resolved the
        # inbox on `uid` alone, so a signed-in user could post a reply into
        # somebody else's support thread. Support staff still reach every
        # ticket; `Inbox` has no company column, so its owning user is the
        # boundary.
        user = self.context["request"].user
        filters = {"uid": self.context["view"].kwargs.get("uid", None)}
        if not user.is_superuser:
            filters["user"] = user

        inbox = get_object_or_404(Inbox.objects.filter(**filters))
        if inbox.status in [
            InboxStatusChoices.CLOSED,
            InboxStatusChoices.REMOVED,
            InboxStatusChoices.COMPLETED,
        ]:
            raise ValidationError({"message": f"Inbox has been {inbox.status}"})
        validated_data["inbox"] = inbox
        return super().validate(validated_data)

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        files = files = validated_data.pop("files", None)
        inbox = validated_data["inbox"]
        inbox.is_seen = False
        inbox.save_dirty_fields()

        # Creating thread
        thread = Thread.objects.create(**validated_data)

        if files:
            file_items = [
                FileItem.objects.create(
                    status=FileItemStatusChoices.PUBLISHED,
                    file=file,
                    kind=get_file_kind(os.path.splitext(file.name)[1]),
                )
                for file in files
            ]

            FileItemConnector.objects.bulk_create(
                [
                    FileItemConnector(
                        model_kind=FileItemConnectorModelKindChoices.THREAD,
                        thread=thread,
                        file_item=file_item,
                    )
                    for file_item in file_items
                ]
            )
        return validated_data
