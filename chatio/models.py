from django.db import models
from django.utils.text import slugify

from common.models import BaseModelWithUID

from .choices import MessageTypeChoices, RoomMemberRoleChoices


class Messages(models.Model):
    receiver = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="received_message"
    )
    sender = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="sent_message"
    )
    content = models.TextField(blank=True, null=True)
    message_type = models.CharField(
        max_length=20,
        choices=MessageTypeChoices.choices,
        default=MessageTypeChoices.TEXT,
    )
    file_data = models.URLField(blank=True, null=True)
    # Chat message lifecycle
    is_active = models.BooleanField(default=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"sender: {self.sender.first_name} receiver: {self.receiver.first_name}"

    class Meta:
        ordering = ["-timestamp"]
        verbose_name_plural = "Messages"


class ChatRoom(BaseModelWithUID):
    slug = models.SlugField(unique=True, db_index=True, max_length=255, blank=True)
    description = models.TextField(blank=True, null=True)
    room_icon_url = models.URLField(blank=True, null=True)
    is_expense_policy_enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_chat_rooms",
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            uid_part = str(self.uid).split("-")[0] if self.uid else ""
            base = slugify(self.title or "room")
            self.slug = f"{base}-{uid_part}" if uid_part else base
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Chat Rooms"

    @property
    def name(self):
        return self.title or ""

    def get_member_count(self):
        if hasattr(self, "_member_count"):
            return self._member_count
        return self.members.count()

    def __str__(self):
        return self.name


class ChatRoomMember(models.Model):
    room = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="chat_room_memberships"
    )
    role = models.CharField(
        max_length=20,
        choices=RoomMemberRoleChoices.choices,
        default=RoomMemberRoleChoices.EMPLOYEE,
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["room", "user"]
        ordering = ["-joined_at"]

    def __str__(self):
        return f"{self.user.email} - {self.room.name} ({self.role})"


class ChatRoomMessage(models.Model):
    room = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="room_messages_sent"
    )
    content = models.TextField(blank=True, null=True)
    message_type = models.CharField(
        max_length=20,
        choices=MessageTypeChoices.choices,
        default=MessageTypeChoices.TEXT,
    )
    file_data = models.URLField(blank=True, null=True)
    origin_message = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="status_updates",
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.sender.email} in {self.room.name}: {self.content[:30]}"


class ChatRoomMessageRead(models.Model):
    message = models.ForeignKey(
        ChatRoomMessage, on_delete=models.CASCADE, related_name="read_receipts"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="room_messages_read"
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["message", "user"]

    def __str__(self):
        return f"{self.user.email} read msg #{self.message_id}"