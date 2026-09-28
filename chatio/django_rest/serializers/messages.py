from rest_framework import serializers

from accounts.models import User

from ...models import Messages


class RecentUsersSerializer(serializers.ModelSerializer):
    last_message_content = serializers.CharField(read_only=True)
    last_message_timestamp = serializers.DateTimeField(read_only=True)
    
    class Meta:
        model = User
        fields = [
            # "id",
            "uid",
            "first_name",
            "middle_name",
            "last_name",
            "image",
            "last_message_content",
            "last_message_timestamp",
        ]


class MessageSerializer(serializers.ModelSerializer):
    sender = RecentUsersSerializer(read_only=True)
    receiver = RecentUsersSerializer(read_only=True)
    class Meta:
        model = Messages
        fields = [
            "id",
            "sender",
            "receiver",
            "content",
            "message_type",
            "file_data",
            "is_read",
            "is_active",
            "timestamp",
            "read_at",
        ]