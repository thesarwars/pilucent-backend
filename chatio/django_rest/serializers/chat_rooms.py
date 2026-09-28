from rest_framework import serializers

from accounts.models import User

from chatio.models import ChatRoom, ChatRoomMember, ChatRoomMessage
from chatio.choices import RoomMemberRoleChoices
from employeeio.models import EmployeeExpenseReport
from .messages import RecentUsersSerializer


def _user_full_name(user):
    """Return 'first_name last_name' or None."""
    if user is None:
        return None
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or None


class ChatRoomCreatorSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "uid", "email", "first_name", "last_name"]


class ChatRoomMemberSerializer(serializers.ModelSerializer):
    user_uid = serializers.UUIDField(source="user.uid", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = ChatRoomMember
        fields = [
            "id",
            "user",
            "user_uid",
            "email",
            "first_name",
            "last_name",
            "role",
            "joined_at",
        ]
        read_only_fields = ["joined_at"]


class ChatRoomListSerializer(serializers.ModelSerializer):
    created_by_detail = ChatRoomCreatorSlimSerializer(
        source="created_by", read_only=True
    )
    member_count = serializers.IntegerField(source="get_member_count", read_only=True)

    class Meta:
        model = ChatRoom
        fields = [
            "uid",
            "title",
            "slug",
            "description",
            "created_by_detail",
            "member_count",
            "room_icon_url",
            # "is_expense_policy_enabled",
            "created_at",
            "updated_at",
        ]


class ChatRoomDetailSerializer(serializers.ModelSerializer):
    created_by_detail = ChatRoomCreatorSlimSerializer(
        source="created_by", read_only=True
    )
    members = ChatRoomMemberSerializer(many=True, read_only=True)

    class Meta:
        model = ChatRoom
        fields = [
            "uid",
            "title",
            "slug",
            "description",
            "created_by_detail",
            "members",
            "room_icon_url",
            "is_expense_policy_enabled",
            "created_at",
            "updated_at",
        ]


class ChatRoomCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatRoom
        fields = [
            "uid",
            "slug",
            "title",
            "description",
            "room_icon_url",
            "is_expense_policy_enabled",
        ]
        read_only_fields = ["uid", "slug"]


class ChatRoomAddMembersSerializer(serializers.Serializer):
    user_uids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="List of user UIDs to add as members",
    )
    role = serializers.ChoiceField(
        choices=RoomMemberRoleChoices.choices,
        default=RoomMemberRoleChoices.EMPLOYEE,
        required=False,
    )


class ChatRoomMemberRoleUpdateSerializer(serializers.ModelSerializer):
    """Only role is writable; used by group admin to change a member's role."""

    class Meta:
        model = ChatRoomMember
        fields = ["role"]


class ChatRoomMessageSerializer(serializers.ModelSerializer):
    sender = RecentUsersSerializer(read_only=True)
    room_uid = serializers.UUIDField(source="room.uid", read_only=True)
    origin_message_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = ChatRoomMessage
        fields = [
            "id",
            "room_uid",
            "sender",
            "content",
            "message_type",
            "file_data",
            "origin_message_id",
            "timestamp",
        ]



class EmployeeExpenseReportSerializer(serializers.ModelSerializer):
    supplier = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    purchase_uid = serializers.SerializerMethodField()
    submitted_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()
    paid_by = serializers.SerializerMethodField()
    rejected_by = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeExpenseReport
        fields = [
            "uid",
            "slug",
            "status_previous",
            "status",
            "amount",
            "currency",
            "vendor_supplier_name",
            "supplier",
            "category",
            "expense_date",
            "payment_date",
            "description",
            "reference_number",
            "file_path",
            "purchase_uid",
            "submitted_by",
            "approved_by",
            "paid_by",
            "rejected_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_supplier(self, obj):
        if not obj.supplier_id:
            return None
        supplier = obj.supplier
        title = supplier.company_name or supplier.display_name or ""
        return {"uid": str(supplier.uid), "title": title}

    def get_category(self, obj):
        if not obj.chart_of_account_id:
            return None
        coa = obj.chart_of_account
        return {"uid": str(coa.uid), "title": coa.title}

    def get_purchase_uid(self, obj):
        if not obj.purchase_id:
            return None
        return str(obj.purchase.uid)

    def get_submitted_by(self, obj):
        if not obj.submitted_by_id:
            return None
        return _user_full_name(obj.submitted_by)

    def get_approved_by(self, obj):
        if not obj.approved_by_id:
            return None
        return _user_full_name(obj.approved_by)

    def get_paid_by(self, obj):
        if not obj.paid_by_id:
            return None
        return _user_full_name(obj.paid_by)

    def get_rejected_by(self, obj):
        if not obj.rejected_by_id:
            return None
        return _user_full_name(obj.rejected_by)
