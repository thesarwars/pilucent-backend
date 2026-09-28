from django.contrib import admin

from .models import (
    Messages,
    ChatRoom,
    ChatRoomMember,
    ChatRoomMessage,
    ChatRoomMessageRead,
)


@admin.register(Messages)
class MessagesAdmin(admin.ModelAdmin):
    list_display = ["content", "message_type", "sender", "receiver", "is_read", "timestamp"]
    list_filter = ["message_type"]
    search_fields = ["content"]


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "slug", "created_by", "created_at"]
    search_fields = ["title", "slug"]
    readonly_fields = ["uid"]


@admin.register(ChatRoomMember)
class ChatRoomMemberAdmin(admin.ModelAdmin):
    list_display = ["room", "user", "role", "joined_at"]
    list_filter = ["role"]


@admin.register(ChatRoomMessage)
class ChatRoomMessageAdmin(admin.ModelAdmin):
    list_display = ["room", "sender", "content", "message_type", "timestamp"]
    list_filter = ["message_type"]
    readonly_fields = ["origin_message_id"]


@admin.register(ChatRoomMessageRead)
class ChatRoomMessageReadAdmin(admin.ModelAdmin):
    list_display = ["message", "user", "read_at"]
