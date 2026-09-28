from rest_framework import serializers
from accounts.models import User
from django.contrib.auth.models import Permission, Group

from adminio.django_rest.helpers.permission_tree import build_permission_tree


class RoleAndPermissionSerializer(serializers.ModelSerializer):
    groups = serializers.StringRelatedField(many=True)  # to show group names
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "groups", "permissions"]

    def get_permissions(self, obj):
        return build_permission_tree(
            Permission.objects.filter(group__user=obj).select_related("content_type")
        )


class GroupPermissionsListSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="name", read_only=True)

    class Meta:
        model = Group
        fields = ["id", "group_name", "permissions"]

    def get_permissions(self, obj):
        return build_permission_tree(obj.permissions.all())
