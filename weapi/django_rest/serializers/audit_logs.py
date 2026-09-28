import re

from auditlog.models import LogEntry

from rest_framework import serializers

from accounts.django_rest.serializers.common import PriateUserSlimSerializer


class PrivateWeAuditLogListSerializer(serializers.ModelSerializer):
    uid = serializers.SerializerMethodField()
    created_by = PriateUserSlimSerializer(source="actor", read_only=True)
    content_name = serializers.SerializerMethodField()
    action = serializers.SerializerMethodField()
    # changes = serializers.SerializerMethodField()

    class Meta:
        model = LogEntry
        fields = [
            "uid",
            "content_name",
            "action",
            "created_by",
            # "changes",
            "timestamp",
        ]

    def get_uid(self, object):
        date_time = str(object.timestamp)
        return f"{int(date_time[0])+object.id}{re.sub(r'[^0-9T]+', '', date_time)}"

    def get_content_name(self, object):
        content_type = object.content_type
        return (
            content_type.model_class()._meta.verbose_name.title()
            if content_type
            else None
        )

    def get_action(self, object):
        return {0: "Create", 1: "Update", 2: "Delete", 3: "View"}.get(
            object.action, "Unknown"
        )

    """
        ⚠️ Note:
        This method is intentionally left unused. Do not activate or modify it
        without a thorough understanding of how the auditlog system works. Misuse can
        lead to inaccurate or misleading change logs.

        Before enabling or customizing this logic, consult with your senior or team lead
        to ensure correct usage and context.
    """

    # def get_changes(self, object):
    #     data = {}
    #     changes = getattr(object, "changes", {}) or {}
    #     for change, values in changes.items():
    #         if isinstance(values, list):
    #             data[change] = {"old_data": values[0], "new_data": values[1]}
    #     return data
