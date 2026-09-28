import logging

from rest_framework import serializers

from django.contrib.auth.models import Permission

from adminio.models import CompanyRole
from adminio.django_rest.helpers.permission_tree import get_report_permissions

from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from companyio.models import CompanyUser


logger = logging.getLogger(__name__)


class CompanyPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "name", "content_type", "codename"]

    def to_representation(self, instance):
        return f"{instance.id} | {instance}"


class CompanyUserPermissionSerializer(serializers.ModelSerializer):
    user_uid = serializers.CharField(write_only=True)
    role_uid = serializers.CharField(write_only=True, required=False)
    role_uids = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    username = serializers.CharField(source="user.name", read_only=True)
    role_names = serializers.SerializerMethodField()
    permission = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = CompanyUser
        fields = [
            "id",
            "user",
            "user_uid",
            "username",
            "roles",
            "role_uid",
            "role_uids",
            "role_names",
            "permission",
            "permissions",
        ]
        extra_kwargs = {"user": {"read_only": True}, "roles": {"read_only": True}}

    def get_role_names(self, obj):
        return [r.name for r in obj.roles.all()]

    def get_permissions(self, obj):
        permission_dict = {}
        for permission in obj.permission.all():
            app_label = permission.content_type.app_label
            model_name = permission.content_type.model
            if app_label not in permission_dict:
                permission_dict[app_label] = []
            model_entry = next(
                (entry for entry in permission_dict[app_label] if model_name in entry),
                None,
            )
            if not model_entry:
                permission_dict[app_label].append({model_name: []})
                model_entry = permission_dict[app_label][-1]
            model_entry[model_name].append(
                {"id": permission.id, "codename": permission.codename}
            )
        return {
            "app_label": [permission_dict],
            "reports": get_report_permissions(obj),
        }

    def update(self, instance, validated_data):
        validated_data.pop("user_uid", None)
        role_uids = validated_data.pop("role_uids", None)
        role_uid = validated_data.pop("role_uid", None)
        permission_ids = validated_data.pop("permission", None)

        actor = self.context["request"].user if "request" in self.context else None
        roles_changed = False
        before_role_names = list(instance.roles.values_list("name", flat=True))

        if role_uids:
            instance.roles.set(CompanyRole.objects.filter(uid__in=role_uids))
            roles_changed = True
        elif role_uid:
            role = CompanyRole.objects.filter(uid=role_uid).first()
            if role:
                instance.roles.set([role])
                roles_changed = True

        if roles_changed:
            after_role_names = list(instance.roles.values_list("name", flat=True))
            crud_log(
                logger,
                CrudAction.ROLES_CHANGED,
                instance,
                actor=actor,
                extra={
                    "user": instance.user.email,
                    "before": "[" + ",".join(before_role_names) + "]",
                    "after": "[" + ",".join(after_role_names) + "]",
                },
            )

        if permission_ids is not None:
            before_perm_ids = set(instance.permission.values_list("id", flat=True))
            instance.permission.set(Permission.objects.filter(id__in=permission_ids))
            after_perm_ids = set(instance.permission.values_list("id", flat=True))
            crud_log(
                logger,
                CrudAction.PERMISSIONS_CHANGED,
                instance,
                actor=actor,
                extra={
                    "user": instance.user.email,
                    "added": len(after_perm_ids - before_perm_ids),
                    "removed": len(before_perm_ids - after_perm_ids),
                },
            )

        instance.save()
        return instance


class CompanyUserPermsListSerializer(serializers.ModelSerializer):
    user_uid = serializers.CharField(write_only=True)
    username = serializers.CharField(source="user.name", read_only=True)
    role_names = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = CompanyUser
        fields = [
            "id",
            "user",
            "user_uid",
            "username",
            "roles",
            "role_names",
            "permissions",
        ]
        extra_kwargs = {"user": {"read_only": True}, "roles": {"read_only": True}}

    def get_role_names(self, obj):
        return [r.name for r in obj.roles.all()]

    def get_permissions(self, obj):
        permission_dict = {}
        for permission in obj.permission.all():
            app_label = permission.content_type.app_label
            model_name = permission.content_type.model
            if app_label not in permission_dict:
                permission_dict[app_label] = {"model": {}}
            if model_name not in permission_dict[app_label]["model"]:
                permission_dict[app_label]["model"][model_name] = []
            permission_dict[app_label]["model"][model_name].append(
                {"id": permission.id, "codename": permission.codename}
            )
        return {
            "app_label": permission_dict,
            "reports": get_report_permissions(obj),
        }
