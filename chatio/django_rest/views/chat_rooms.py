import json

from django.db.models import Count

from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, NotFound

from chatio.models import ChatRoom, ChatRoomMember
from chatio.models import ChatRoomMessage
from chatio.choices import RoomMemberRoleChoices, MessageTypeChoices
from chatio.django_rest.permissions import IsRoomMember, IsGroupAdmin
from chatio.pagination import MessagePagination
from chatio.django_rest.serializers import (
    ChatRoomListSerializer,
    ChatRoomDetailSerializer,
    ChatRoomCreateUpdateSerializer,
    ChatRoomAddMembersSerializer,
    ChatRoomMemberRoleUpdateSerializer,
    ChatRoomMemberSerializer,
    ChatRoomMessageSerializer,
    EmployeeExpenseReportSerializer,
)

from accounts.models import User
from employeeio.models import EmployeeExpenseReport


def get_chat_room_queryset(user):
    base = ChatRoom.objects.annotate(_member_count=Count("members"))
    if not user.is_authenticated:
        return base.none()
    if getattr(user, "is_superuser", False) or getattr(user, "is_admin", False):
        return base.distinct()
    return base.filter(members__user=user).distinct()


class ChatRoomListCreateView(generics.ListCreateAPIView):
    """
    GET: list rooms (user must be member or admin).
    POST: create room (authenticated).
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_chat_room_queryset(self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ChatRoomCreateUpdateSerializer
        return ChatRoomListSerializer

    def perform_create(self, serializer):
        room = serializer.save(created_by=self.request.user)
        ChatRoomMember.objects.get_or_create(
            room=room,
            user=self.request.user,
            defaults={"role": RoomMemberRoleChoices.GROUP_ADMIN},
        )


class ChatRoomRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: retrieve room (must be member).
    PUT/PATCH: update room (must be GROUP_ADMIN).
    DELETE: delete room (must be GROUP_ADMIN).
    """
    lookup_field = "uid"

    def get_queryset(self):
        return get_chat_room_queryset(self.request.user)

    def get_serializer_class(self):
        if self.request.method == "GET":
            return ChatRoomDetailSerializer
        return ChatRoomCreateUpdateSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsRoomMember()]
        return [IsAuthenticated(), IsGroupAdmin()]


class ChatRoomAddMembersView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsGroupAdmin]
    serializer_class = ChatRoomAddMembersSerializer
    lookup_field = "uid"

    def get_queryset(self):
        return get_chat_room_queryset(self.request.user)

    def post(self, request, *args, **kwargs):
        room = self.get_object()
        self.check_object_permissions(request, room)

        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user_uids = ser.validated_data["user_uids"]
        role = ser.validated_data.get("role", "EMPLOYEE")

        users = User.objects.filter(uid__in=user_uids)
        found_uids = set(users.values_list("uid", flat=True))
        not_found_uids = [str(uid) for uid in user_uids if uid not in found_uids]
        if not_found_uids:
            raise ValidationError(
                {"user_uids": f"No user found for uid(s): {', '.join(not_found_uids)}"}
            )

        created = []
        for user in users:
            member, created_flag = ChatRoomMember.objects.get_or_create(
                room=room,
                user=user,
                defaults={"role": role},
            )
            if created_flag:
                created.append(member)

        detail_ser = ChatRoomDetailSerializer(room)
        return Response(
            {
                "message": f"Added {len(created)} member(s).",
                "room": detail_ser.data,
            },
            status=status.HTTP_200_OK,
        )


class ChatRoomMemberDetailView(generics.GenericAPIView):
    """
    PATCH: Group admin can change a member's role in the room.
    DELETE: Group admin can remove/detach a member from the room.

    URL: /rooms/<room_uid>/members/<user_uid>/
    PATCH body: { "role": "MODERATOR" | "APPROVER" | "FINANCE" | "EMPLOYEE" | ... }
    """
    permission_classes = [IsAuthenticated, IsGroupAdmin]
    serializer_class = ChatRoomMemberRoleUpdateSerializer
    http_method_names = ["patch", "put", "delete", "options"]

    def get_object(self):
        room_uid = self.kwargs.get("uid")
        user_uid = self.kwargs.get("user_uid")
        room = get_chat_room_queryset(self.request.user).filter(uid=room_uid).first()
        if not room:
            raise NotFound("Room not found.")
        self.check_object_permissions(self.request, room)
        member = ChatRoomMember.objects.filter(room=room, user__uid=user_uid).first()
        if not member:
            raise NotFound("Member not found in this room.")
        return member

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ChatRoomMemberSerializer(instance).data)

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ChatRoomMemberSerializer(instance).data)

    def delete(self, request, *args, **kwargs):
        member = self.get_object()
        room = member.room

        # Prevent admins from removing themselves via this endpoint (they should
        # use the leave endpoint and transfer ownership first if needed).
        if member.user_id == request.user.id:
            raise ValidationError(
                {"detail": "Group admins cannot remove themselves. Use leave room instead."}
            )

        # Prevent removing the room creator.
        if room.created_by_id and member.user_id == room.created_by_id:
            raise ValidationError(
                {"detail": "The room creator cannot be removed."}
            )

        removed_data = ChatRoomMemberSerializer(member).data
        member.delete()
        return Response(
            {
                "message": "Member removed from room.",
                "room_uid": str(room.uid),
                "member": removed_data,
            },
            status=status.HTTP_200_OK,
        )


class ChatRoomLeaveView(generics.GenericAPIView):
    """
    DELETE: Current user leaves the room.

    URL: /rooms/<room_uid>/leave/

    Rules:
    - The room creator cannot leave their own room (they must transfer ownership
      or delete the room).
    - If the last GROUP_ADMIN tries to leave while other members exist, the
      action is blocked to avoid leaving the room without an admin.
    """
    permission_classes = [IsAuthenticated, IsRoomMember]
    http_method_names = ["delete", "options"]

    def get_object(self):
        room_uid = self.kwargs.get("uid")
        room = get_chat_room_queryset(self.request.user).filter(uid=room_uid).first()
        if not room:
            raise NotFound("Room not found.")
        self.check_object_permissions(self.request, room)
        return room

    def delete(self, request, *args, **kwargs):
        room = self.get_object()
        membership = ChatRoomMember.objects.filter(room=room, user=request.user).first()
        if not membership:
            raise NotFound("You are not a member of this room.")

        if room.created_by_id == request.user.id:
            raise ValidationError(
                {"detail": "The room creator cannot leave. Transfer ownership or delete the room."}
            )

        if membership.role == RoomMemberRoleChoices.GROUP_ADMIN:
            other_admins = ChatRoomMember.objects.filter(
                room=room, role=RoomMemberRoleChoices.GROUP_ADMIN
            ).exclude(user=request.user).exists()
            has_other_members = ChatRoomMember.objects.filter(room=room).exclude(
                user=request.user
            ).exists()
            if has_other_members and not other_admins:
                raise ValidationError(
                    {"detail": "Promote another member to GROUP_ADMIN before leaving."}
                )

        membership.delete()
        return Response(
            {
                "message": "You have left the room.",
                "room_uid": str(room.uid),
            },
            status=status.HTTP_200_OK,
        )


class ChatRoomMessageListView(generics.ListAPIView):
    """List messages for a given chat room (room uid in URL)."""
    permission_classes = [IsAuthenticated, IsRoomMember]
    serializer_class = ChatRoomMessageSerializer
    pagination_class = MessagePagination

    def get_queryset(self):
        room_uid = self.kwargs.get("uid")
        room = get_chat_room_queryset(self.request.user).filter(uid=room_uid).first()
        if not room:
            raise NotFound("Room not found.")
        # ensure the user has membership permission checked via IsRoomMember
        self.check_object_permissions(self.request, room)
        return ChatRoomMessage.objects.filter(room=room).order_by("-timestamp")

    def _extract_expense_payload(self, message):
        """Return expense event payload if message content stores it as JSON."""
        if message.message_type != MessageTypeChoices.EXPENSE_DATA:
            return None
        if not message.content:
            return None
        try:
            payload = json.loads(message.content)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None

        event = payload.get("event")
        if event not in ("expense_report_saved", "expense_report_status_changed"):
            return None
        return {
            "event": event,
            "deposit_to": payload.get("deposit_to"),
            "payment_method": payload.get("payment_method"),
            "result": payload.get("result"),
        }

    def _build_report_file_data(self, report_uid):
        """Fetch EmployeeExpenseReport by uid and build file_data matching socket format."""
        if not report_uid:
            return None
        report = EmployeeExpenseReport.objects.filter(uid=report_uid).first()
        if not report:
            return None
        return EmployeeExpenseReportSerializer(report).data

    def _apply_expense_payload(self, serialized_item, expense_payload):
        """Reshape expense messages so REST output matches WebSocket format."""
        if not expense_payload:
            return
        result = expense_payload.get("result") or {}
        report_uid = result.get("uid")
        file_data = self._build_report_file_data(report_uid)
        serialized_item["content"] = ""
        serialized_item["file_data"] = file_data or result
        serialized_item["event"] = expense_payload.get("event")
        serialized_item["deposit_to"] = expense_payload.get("deposit_to")
        serialized_item["payment_method"] = expense_payload.get("payment_method")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response_data = serializer.data
            for index, message in enumerate(page):
                if message.message_type != MessageTypeChoices.EXPENSE_DATA:
                    continue
                expense_payload = self._extract_expense_payload(message)
                self._apply_expense_payload(response_data[index], expense_payload)
            return self.get_paginated_response(response_data)

        serializer = self.get_serializer(queryset, many=True)
        response_data = serializer.data
        for index, message in enumerate(queryset):
            if message.message_type != MessageTypeChoices.EXPENSE_DATA:
                continue
            expense_payload = self._extract_expense_payload(message)
            self._apply_expense_payload(response_data[index], expense_payload)
        return Response(response_data)

