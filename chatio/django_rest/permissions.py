from rest_framework.permissions import BasePermission, IsAuthenticated
from employeeio.models import Employee
from chatio.models import ChatRoom, ChatRoomMember
from chatio.choices import RoomMemberRoleChoices

class IsAdmin(BasePermission):
    message = "Admin access required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            getattr(request.user, "is_superuser", False)
            or getattr(request.user, "is_admin", False)
            or getattr(request.user, "is_staff", False)
        )


class IsEmployee(BasePermission):
    message = "Employee access required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            return Employee.objects.filter(user=request.user).exists()
        except Exception:
            return False


class IsRoomMember(BasePermission):
    message = "You must be a member of this room to access it."

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        room = obj if isinstance(obj, ChatRoom) else getattr(obj, "room", None)
        if not room:
            return False
        return ChatRoomMember.objects.filter(room=room, user=request.user).exists()


class IsGroupAdmin(BasePermission):
    message = "You must be a group admin of this room to perform this action."

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        room = obj if isinstance(obj, ChatRoom) else getattr(obj, "room", None)
        if not room:
            return False
        member = ChatRoomMember.objects.filter(room=room, user=request.user).first()
        return member is not None and member.role == RoomMemberRoleChoices.GROUP_ADMIN
