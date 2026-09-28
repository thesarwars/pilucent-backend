import json
from uuid import UUID

from channels.generic.websocket import AsyncWebsocketConsumer

from asgiref.sync import sync_to_async

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from accounts.models import User

from ...models import Messages, ChatRoom, ChatRoomMember, ChatRoomMessage, ChatRoomMessageRead

from ...choices import MessageTypeChoices
from ..serializers.messages import RecentUsersSerializer
from ..helpers.expense_report import save_employee_expense_report, change_expense_report_status


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.receiver_uid = self.scope["url_route"]["kwargs"]["receiver_uid"]
        self.receiver = await sync_to_async(lambda: User.objects.get(uid=self.receiver_uid))()
        # print('receiver', self.receiver)
        # rec_user = User.objects.get(uid=self.receiver_id)
        # rec_user.id

        if self.user == AnonymousUser():
            await self.close()
            return

        user_ids = sorted([self.user.id, int(self.receiver.id)])
        self.room_group_name = f"chat_{user_ids[0]}_{user_ids[1]}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        # Mark current user as recently seen when they join the chat
        # await self._update_user_last_seen()

        await self.accept()

        # Notify both participants that this user is online in this chat
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_status",
                "user_id": self.user.id,
                "status": "online",
            },
        )

    async def disconnect(self, code):
        if not getattr(self, "room_group_name", None):
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_status",
                "user_id": self.user.id,
                "status": "offline",
            },
        )
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """
        Handles incoming WebSocket messages.
        Expected JSON structure:
        {
            "message": "Hello",
            "message_type": "text",  # or 'image', 'file', 'voice'
            "file_data": "base64-encoded" or URL if browser-stored
        }
        """

        data = json.loads(text_data)

        # Special action: mark all messages in this conversation as read
        action = data.get("action")
        if action == "mark_read":
            updated_count = await self._mark_messages_read()
            if updated_count:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "messages_read",
                        "reader_id": self.user.id,
                        "other_id": self.receiver.id,
                    },
                )
            return

        # if action == "save_expense_report":
        #     result = await self._save_employee_expense_report(data.get("data", {}))
        #     payload = {
        #         "event": "expense_report_saved",
        #         "user_uid": str(self.user.uid),
        #         "first_name": self.user.first_name or "",
        #         "last_name": self.user.last_name or "",
        #         "user_email": self.user.email or "",
        #         "file_path": result.get("file_path") if isinstance(result, dict) else None,
        #         "result": result,
        #     }
        #     await self.save_message(
        #         receiver=self.receiver,
        #         message=json.dumps(payload),
        #         message_type=MessageTypeChoices.EXPENSE_DATA,
        #         file_data=payload.get("file_path"),
        #     )
        #     await self.channel_layer.group_send(
        #         self.room_group_name,
        #         {"type": "expense_report_saved_broadcast", "payload": payload},
        #     )
        #     return

        # if action == "change_expense_report_status":
        #     result = await self._change_expense_report_status(data.get("data", {}))
        #     payload = {
        #         "event": "expense_report_status_changed",
        #         "user_uid": str(self.user.uid),
        #         "first_name": self.user.first_name or "",
        #         "last_name": self.user.last_name or "",
        #         "user_email": self.user.email or "",
        #         "deposit_to": result.get("deposit_to") if isinstance(result, dict) else None,
        #         "payment_method": result.get("payment_method") if isinstance(result, dict) else None,
        #         "result": result,
        #     }
        #     await self.save_message(
        #         receiver=self.receiver,
        #         message=json.dumps(payload),
        #         message_type=MessageTypeChoices.EXPENSE_DATA,
        #         file_data=None,
        #     )
        #     await self.channel_layer.group_send(
        #         self.room_group_name,
        #         {"type": "expense_report_status_changed_broadcast", "payload": payload},
        #     )
        #     return

        message = data.get("message", "")
        message_type = data.get("message_type", MessageTypeChoices.TEXT)
        file_data = data.get("file_data", None)

        receiver = await sync_to_async(lambda: User.objects.get(uid=self.receiver_uid))()

        msg_obj = await self.save_message(receiver, message, message_type, file_data)
        
        sender_serializerd = await sync_to_async(lambda: RecentUsersSerializer(self.user).data)()
        receiver_serializerd = await sync_to_async(lambda: RecentUsersSerializer(receiver).data)()

        response = {
            "event": "new_message",
            "id": msg_obj.id,
            "receiver": receiver_serializerd,
            "sender": sender_serializerd,
            "content": message,
            "message_type": message_type,
            "file_data": file_data,
            "is_read": msg_obj.is_read,
            "timestamp": str(msg_obj.timestamp),
        }

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "message": response,
                # "sender_id": self.user.id,
            },
        )

        # Notify both users' conversation-list consumers to refresh
        for uid in (self.user.id, receiver.id):
            await self.channel_layer.group_send(
                f"user_list_{uid}",
                {"type": "conversation_update"},
            )

    async def chat_message(self, event):
        if event.get("sender_id") == self.user.id:
            return
        await self.send(text_data=json.dumps(event["message"]))

    @sync_to_async
    def save_message(self, receiver, message, message_type, file_data):
        return Messages.objects.create(
            receiver=receiver,
            sender=self.user,
            content=message,
            message_type=message_type,
            file_data=file_data,
        )

    async def user_status(self, event):
        """Broadcasted when a participant connects/disconnects.

        Payload example sent to frontend:
        {"event": "user_status", "user_id": 1, "status": "online"}
        """

        await self.send(
            text_data=json.dumps(
                {
                    "event": "user_status",
                    "user_id": event["user_id"],
                    "status": event["status"],
                }
            )
        )

    async def messages_read(self, event):
        """Notify both sides that messages in this conversation were marked read."""

        await self.send(
            text_data=json.dumps(
                {
                    "event": "messages_read",
                    "reader_id": event["reader_id"],
                    "other_id": event["other_id"],
                }
            )
        )

    # async def expense_report_saved_broadcast(self, event):
    #     await self.send(text_data=json.dumps(event["payload"]))

    # async def expense_report_status_changed_broadcast(self, event):
    #     await self.send(text_data=json.dumps(event["payload"]))

    @sync_to_async
    def _mark_messages_read(self):
        """Mark all unread messages from receiver -> current user as read."""

        return Messages.objects.filter(
            sender=self.receiver,
            receiver=self.user,
            is_read=False,
            is_active=True,
        ).update(is_read=True, read_at=timezone.now())

    # @sync_to_async
    # def _save_employee_expense_report(self, data):
    #     return save_employee_expense_report(self.user, data)

    # @sync_to_async
    # def _change_expense_report_status(self, data):
    #     return change_expense_report_status(self.user, data)


class RoomChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.room_uid = self.scope["url_route"]["kwargs"]["room_uid"]

        if self.user == AnonymousUser():
            await self.close(code=4401)
            return

        self.chat_room, self.member = await self._get_room_and_member()
        if not self.chat_room:
            await self.close(code=4404)
            return
        if not self.member:
            await self.close(code=4403)
            return

        self.room_group_name = f"room_{self.chat_room.slug}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        await self.send(
            text_data=json.dumps({
                "event": "room_joined",
                "room_id": str(self.chat_room.uid),
                "room_name": self.chat_room.title,
                "room_slug": self.chat_room.slug,
                "your_role": self.member.role,
            })
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "room_user_status",
                "room_name": self.chat_room.name,
                "room_slug": self.chat_room.slug,
                "user_uid": str(self.user.uid),
                "first_name": self.user.first_name or "",
                "user_email": self.user.email,
                "role": self.member.role,
                "status": "joined",
            },
        )

    @sync_to_async
    def _get_room_and_member(self):
        """Room must exist and user must be a member (from token); no create."""
        try:
            uid = UUID(str(self.room_uid)) if isinstance(self.room_uid, str) else self.room_uid
        except (ValueError, TypeError):
            return None, None
        room = ChatRoom.objects.filter(uid=uid).first()
        if not room:
            return None, None
        member = ChatRoomMember.objects.filter(room=room, user=self.user).first()
        return room, member

    async def disconnect(self, code):
        if not getattr(self, "room_group_name", None):
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "room_user_status",
                "room_name": self.chat_room.title,
                "room_slug": self.chat_room.slug,
                "user_uid": str(self.user.uid),
                "first_name": self.user.first_name or "",
                "user_email": self.user.email,
                "role": self.member.role,
                "status": "left",
            },
        )
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        data = json.loads(text_data)

        action = data.get("action")
        if action == "mark_read":
            result = await self._mark_messages_read(data.get("message_ids"))
            if result:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "room_message_read_broadcast",
                        "payload": result,
                    },
                )
            return

        if action == "save_expense_report":
            result = await self._save_employee_expense_report(data.get("data", {}))
            if not isinstance(result, dict) or not result.get("success"):
                await self.send(text_data=json.dumps({
                    "event": "error",
                    "action": "save_expense_report",
                    "error": result.get("error", "Failed to save expense report") if isinstance(result, dict) else "Unexpected error",
                }))
                return
            payload = {
                "event": "expense_report_saved",
                "room_name": self.chat_room.name,
                "room_slug": self.chat_room.slug,
                "user_uid": str(self.user.uid),
                "first_name": self.user.first_name or "",
                "last_name": self.user.last_name or "",
                "user_email": self.user.email or "",
                "user_image": self.user.image.url if self.user.image else None,
                "role": self.member.role,
                "file_path": result.get("file_path"),
                "result": result,
            }
            message = await self._save_room_expense_event(payload)
            payload["message_id"] = message.id
            await self.channel_layer.group_send(
                self.room_group_name,
                {"type": "expense_report_saved_broadcast", "payload": payload},
            )
            return

        if action == "change_expense_report_status":
            action_data = data.get("data", {})
            origin_msg_id = action_data.get("origin_message_id")
            result = await self._change_expense_report_status(action_data)
            if not isinstance(result, dict) or not result.get("success"):
                await self.send(text_data=json.dumps({
                    "event": "error",
                    "action": "change_expense_report_status",
                    "error": result.get("error", "Failed to change expense report status") if isinstance(result, dict) else "Unexpected error",
                }))
                return
            payload = {
                "event": "expense_report_status_changed",
                "room_name": self.chat_room.name,
                "room_slug": self.chat_room.slug,
                "user_uid": str(self.user.uid),
                "first_name": self.user.first_name or "",
                "last_name": self.user.last_name or "",
                "user_email": self.user.email or "",
                "user_image": self.user.image.url if self.user.image else None,
                "role": self.member.role,
                "origin_message_id": origin_msg_id,
                "deposit_to": result.get("deposit_to"),
                "payment_method": result.get("payment_method"),
                "result": result,
            }
            message = await self._save_room_expense_event(payload)
            payload["message_id"] = message.id
            await self.channel_layer.group_send(
                self.room_group_name,
                {"type": "expense_report_status_changed_broadcast", "payload": payload},
            )
            return

        message = data.get("message", "")
        message_type = str(data.get("message_type", MessageTypeChoices.TEXT)).upper()
        file_data = data.get("file_data")

        msg_obj = await self._save_room_message(message, message_type, file_data)
        read_count, read_by = await self._get_message_read_info(msg_obj.id)

        payload = {
            "event": "room_message",
            "id": msg_obj.id,
            "sender": {
                "id": self.user.id,
                "uid": str(self.user.uid),
                "first_name": self.user.first_name or "",
                "last_name": self.user.last_name or "",
                "role": self.member.role,
                "image": self.user.image.url if self.user.image else None,
            },
            "content": message,
            "message_type": message_type,
            "file_data": file_data,
            "created_time": msg_obj.timestamp.isoformat(),
            "read_count": read_count,
            "read_by": read_by,
        }

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "room_message_broadcast", "payload": payload},
        )

        # Notify all room members' conversation-list consumers to refresh
        member_ids = await self._get_room_member_ids()
        for mid in member_ids:
            await self.channel_layer.group_send(
                f"user_list_{mid}",
                {"type": "conversation_update"},
            )

    @sync_to_async
    def _save_room_message(self, content, message_type, file_data):
        return ChatRoomMessage.objects.create(
            room=self.chat_room,
            sender=self.user,
            content=content,
            message_type=message_type,
            file_data=file_data,
        )

    @sync_to_async
    def _save_room_expense_event(self, payload):
        return ChatRoomMessage.objects.create(
            room=self.chat_room,
            sender=self.user,
            content=json.dumps(payload),
            message_type=MessageTypeChoices.EXPENSE_DATA,
            file_data=payload.get("file_path"),
            origin_message_id=payload.get("origin_message_id"),
        )

    @sync_to_async
    def _save_employee_expense_report(self, data):
        return save_employee_expense_report(self.user, data)

    @sync_to_async
    def _change_expense_report_status(self, data):
        return change_expense_report_status(self.user, data, member=self.member)

    @sync_to_async
    def _get_room_member_ids(self):
        return list(
            ChatRoomMember.objects.filter(room=self.chat_room).values_list("user_id", flat=True)
        )

    @sync_to_async
    def _get_message_read_info(self, message_id):
        reads = list(
            ChatRoomMessageRead.objects.filter(message_id=message_id).values_list(
                "user_id", "read_at"
            )
        )
        read_by = [{"user_id": r[0], "read_at": r[1].isoformat()} for r in reads]
        return len(reads), read_by

    @sync_to_async
    def _mark_messages_read(self, message_ids=None):
        if message_ids:
            messages = ChatRoomMessage.objects.filter(
                id__in=message_ids, room=self.chat_room
            )
        else:
            messages = ChatRoomMessage.objects.filter(room=self.chat_room).exclude(
                sender=self.user
            )
        created = []
        for msg in messages:
            _, created_flag = ChatRoomMessageRead.objects.get_or_create(
                message=msg, user=self.user
            )
            if created_flag:
                created.append(msg.id)
        if not created:
            return None
        read_count_map = {}
        for msg_id in created:
            cnt = ChatRoomMessageRead.objects.filter(message_id=msg_id).count()
            read_by = list(
                ChatRoomMessageRead.objects.filter(message_id=msg_id).values(
                    "user_id", "read_at"
                )
            )
            read_count_map[str(msg_id)] = {
                "read_count": cnt,
                "read_by": [{"user_id": r["user_id"], "read_at": str(r["read_at"])} for r in read_by],
            }
        return {
            "event": "room_messages_read",
            "reader": {
                "user_id": self.user.id,
                "user_uid": str(self.user.uid),
                "first_name": self.user.first_name or "",
            },
            "message_ids": created,
            "read_info": read_count_map,
        }

    async def room_message_broadcast(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def expense_report_saved_broadcast(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def expense_report_status_changed_broadcast(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def room_message_read_broadcast(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def room_user_status(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "event": "room_user_status",
                    "room_name": event.get("room_name"),
                    "room_slug": event.get("room_slug"),
                    "user_uid": event.get("user_uid"),
                    "first_name": event.get("first_name"),
                    "user_email": event.get("user_email"),
                    "role": event.get("role"),
                    "status": event["status"],
                }
            )
        )
