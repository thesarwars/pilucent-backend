import json

from channels.generic.websocket import AsyncWebsocketConsumer

from asgiref.sync import sync_to_async

from django.contrib.auth.models import AnonymousUser
from django.db.models import Q, Max, Count, Subquery, OuterRef, F, Value, CharField
from django.db.models.functions import Coalesce

from accounts.models import User

from ...models import Messages, ChatRoom, ChatRoomMember, ChatRoomMessage, ChatRoomMessageRead


# Track connected user channel names so we can push updates and resolve online status
_online_users: dict[int, set[str]] = {}


class MessageUserListConsumer(AsyncWebsocketConsumer):
    """
    WebSocket that streams the authenticated user's conversation list.

    Sends on connect (and whenever a refresh is requested):
    {
        "event": "user_list",
        "single_chats": [
            {
                "user": { "uid", "first_name", "last_name", "image", "email" },
                "online": true/false,
                "unread_count": 3,
                "last_message": "Hello",
                "last_message_time": "2026-03-14T..."
            },
            ...
        ],
        "room_chats": [
            {
                "room": { "uid", "title", "slug" },
                "unread_count": 2,
                "last_message": "See you",
                "last_message_time": "2026-03-14T...",
                "last_message_sender": { "uid", "first_name" }
            },
            ...
        ]
    }

    Client can send:
        {"action": "refresh"}   → re-fetch and push the full list
    """

    async def connect(self):
        self.user = self.scope["user"]

        if self.user == AnonymousUser() or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        # Personal group so other consumers can push updates to this user
        self.personal_group = f"user_list_{self.user.id}"

        # Global presence group – every connected user joins this
        self.presence_group = "presence_global"

        await self.channel_layer.group_add(self.personal_group, self.channel_name)
        await self.channel_layer.group_add(self.presence_group, self.channel_name)

        # Track online status
        _online_users.setdefault(self.user.id, set()).add(self.channel_name)

        await self.accept()

        # Send the initial conversation list
        data = await self._build_user_list()
        await self.send(text_data=json.dumps(data))

        # Broadcast to all connected user-list consumers that this user came online
        await self.channel_layer.group_send(
            self.presence_group,
            {
                "type": "presence_update",
                "user_id": self.user.id,
                "online": True,
            },
        )
        
        # await self.send(
        #     text_data=json.dumps({
        #         "event": "room_joined",
        #         "room_id": str(self.chat_room.uid),
        #         "room_name": self.chat_room.title,
        #         "room_slug": self.chat_room.slug,
        #         "your_role": self.member.role,
        #     })
        # )

    async def disconnect(self, code):
        if not getattr(self, "personal_group", None):
            return

        channels = _online_users.get(self.user.id, set())
        channels.discard(self.channel_name)
        if not channels:
            _online_users.pop(self.user.id, None)

        await self.channel_layer.group_send(
            self.presence_group,
            {
                "type": "presence_update",
                "user_id": self.user.id,
                "online": bool(_online_users.get(self.user.id)),
            },
        )

        await self.channel_layer.group_discard(self.personal_group, self.channel_name)
        await self.channel_layer.group_discard(self.presence_group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        data = json.loads(text_data)
        action = data.get("action")

        if action == "refresh":
            payload = await self._build_user_list()
            await self.send(text_data=json.dumps(payload))

    # ─── helpers ──────────────────────────────────────────────────────────

    @sync_to_async
    def _build_user_list(self):
        user = self.user
        single_chats = self._get_single_chats(user)
        room_chats = self._get_room_chats(user)
        return {
            "event": "user_list",
            "single_chats": single_chats,
            "room_chats": room_chats,
        }

    def _get_single_chats(self, user):
        """Return users with whom the current user has exchanged direct messages."""
        user_id = user.id

        # Collect unique partner IDs using explicit _id fields
        sent_to = set(
            Messages.objects.filter(sender_id=user_id, is_active=True)
            .values_list("receiver_id", flat=True)
            .distinct()
        )
        received_from = set(
            Messages.objects.filter(receiver_id=user_id, is_active=True)
            .values_list("sender_id", flat=True)
            .distinct()
        )
        partner_ids = sent_to | received_from

        # Fetch all partners in one query
        partners = {u.id: u for u in User.objects.filter(id__in=partner_ids)}

        results = []
        for pid, partner in partners.items():
            # Last message between user and partner
            last_msg = (
                Messages.objects.filter(
                    Q(sender_id=user_id, receiver_id=pid)
                    | Q(sender_id=pid, receiver_id=user_id),
                    is_active=True,
                )
                .order_by("-timestamp")
                .first()
            )

            # Unread count: messages FROM partner TO current user that are unread
            unread_count = Messages.objects.filter(
                sender_id=pid,
                receiver_id=user_id,
                is_read=False,
                is_active=True,
            ).count()
            # print(f"User {user_id} has {unread_count} unread messages from {pid}")
            results.append(
                {
                    "user": {
                        "uid": str(partner.uid),
                        "first_name": partner.first_name or "",
                        "last_name": partner.last_name or "",
                        "image": partner.image.url if partner.image else None,
                        "email": partner.email,
                    },
                    "online": bool(_online_users.get(pid)),
                    "unread_count": unread_count,
                    "last_message": last_msg.content if last_msg else None,
                    "last_message_time": last_msg.timestamp.isoformat() if last_msg else None,
                }
            )

        # Sort by last_message_time descending (most recent first)
        results.sort(key=lambda x: x["last_message_time"] or "", reverse=True)
        return results

    def _get_room_chats(self, user):
        """Return chat rooms the user is a member of, with unread count and last message."""
        user_id = user.id

        memberships = ChatRoomMember.objects.filter(user_id=user_id).select_related("room")
        results = []

        for membership in memberships:
            room = membership.room

            last_msg = (
                ChatRoomMessage.objects.filter(room=room)
                .order_by("-timestamp")
                .select_related("sender")
                .first()
            )

            # Unread = room messages not sent by user that have no read receipt from user
            unread_count = (
                ChatRoomMessage.objects.filter(room=room)
                .exclude(sender_id=user_id)
                .exclude(read_receipts__user_id=user_id)
                .count()
            )

            last_sender = None
            if last_msg:
                last_sender = {
                    "uid": str(last_msg.sender.uid),
                    "first_name": last_msg.sender.first_name or "",
                }

            results.append(
                {
                    "room": {
                        "uid": str(room.uid),
                        "title": room.title if hasattr(room, "title") else room.name,
                        "slug": room.slug,
                        "room_icon_url": room.room_icon_url,
                    },
                    "unread_count": unread_count,
                    "last_message": last_msg.content if last_msg else None,
                    "last_message_time": last_msg.timestamp.isoformat() if last_msg else None,
                    "last_message_sender": last_sender,
                }
            )

        results.sort(key=lambda x: x["last_message_time"] or "", reverse=True)
        return results

    # ─── group event handlers ────────────────────────────────────────────

    async def presence_update(self, event):
        """Another user came online/offline – push a lightweight status update."""
        await self.send(
            text_data=json.dumps(
                {
                    "event": "presence_update",
                    "user_id": event["user_id"],
                    "online": event["online"],
                }
            )
        )

    async def conversation_update(self, event):
        """Triggered when a new message arrives – push a full refresh of the list."""
        payload = await self._build_user_list()
        await self.send(text_data=json.dumps(payload))
