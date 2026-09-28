from rest_framework.serializers import ModelSerializer, CharField

from ...models import User, ChartOfAccount


class UserBaseSerializer(ModelSerializer):
    is_agent = CharField(source="get_is_agent", read_only=True)

    class Meta:
        model = User
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "name",
            "is_admin",
            "is_agent",
            "image",
            "salutation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PriateUserSlimSerializer(UserBaseSerializer):
    class Meta:
        model = UserBaseSerializer.Meta.model
        fields = ["uid"] + UserBaseSerializer.Meta.fields


class PublicUserSlimSerializer(UserBaseSerializer):
    class Meta:
        model = UserBaseSerializer.Meta.model
        fields = ["slug"] + UserBaseSerializer.Meta.fields


class PrivateChartOfAccountSlimSerializer(ModelSerializer):
    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "code",
            "kind",
            "status",
            "opening_balance",
            "is_fixed",
            "created_at",
            "updated_at",
        ]
