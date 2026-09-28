from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
)
from categoryio.models import Category
from categoryio.django_rest.serializers.common import PrivateCategorySlimSerializer

from common.django_rest.helpers.decorators import set_auditlog_actor

class PrivateWeCategoryListSerializer(ModelSerializer):
    parent = PrivateCategorySlimSerializer(read_only=True)
    parent_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Category.objects.get_status_all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Category
        fields = [
            "uid",
            "title",
            "parent",
            "parent_uid",
            "kind",
            "status",
            "description",
        ]

        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["parent"] = validated_data.pop("parent_uid", None)
        return super().create(validated_data)


class PrivateWeCategoryDetailsSerializer(ModelSerializer):
    parent = PrivateCategorySlimSerializer(read_only=True)
    parent_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Category.objects.get_status_all().filter(),
        write_only=True,
    )

    class Meta:
        model = Category
        fields = [
            "uid",
            "title",
            "parent",
            "parent_uid",
            "kind",
            "status",
            "description",
        ]

        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)

    @set_auditlog_actor
    def update(self, instance, validated_data):
        validated_data["parent"] = validated_data.pop("parent_uid", None)
        return super().update(instance, validated_data)
