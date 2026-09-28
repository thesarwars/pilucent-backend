import logging

from rest_framework import serializers

from django.contrib.auth.models import Permission

from accounts.django_rest.helpers.group_seeds import SYSTEM_ROLE_DISPLAY_LABELS
from accounts.models import User

from adminio.models import CompanyRole
from adminio.django_rest.serializers.user_permissions import CompanyPermissionSerializer

from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from companyio.models import Company


def _role_display_name(role):
    """Friendly label for system roles, plain `name` for custom roles."""
    if getattr(role, "is_system", False):
        return SYSTEM_ROLE_DISPLAY_LABELS.get(role.name, role.name)
    return role.name


logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["uid", "email", "name", "image"]


class RoleSerializer(serializers.ModelSerializer):
    company_uid = serializers.CharField(write_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    permission = serializers.ListField(
        child=serializers.IntegerField(), write_only=True
    )
    permissions = CompanyPermissionSerializer(
        source="permission", many=True, read_only=True
    )

    class Meta:
        model = CompanyRole
        fields = [
            "uid",
            "name",
            "kind",
            "is_system",
            "description",
            "status",
            "company",
            "company_uid",
            "company_name",
            "permission",
            "permissions",
        ]
        extra_kwargs = {
            "company": {"read_only": True},
            "is_system": {"read_only": True},
        }

    def create(self, validated_data):
        company_uid = validated_data.pop("company_uid")
        company = Company.objects.get(uid=company_uid)
        permission_ids = validated_data.pop("permission", [])
        instance = CompanyRole.objects.create(company=company, **validated_data)
        if permission_ids:
            instance.permission.set(Permission.objects.filter(id__in=permission_ids))

        crud_log(
            logger,
            CrudAction.CREATED,
            instance,
            actor=self.context["request"].user if "request" in self.context else None,
            extra={
                "company": company.name,
                "kind": instance.kind,
                "permission_count": len(permission_ids),
            },
        )
        return instance


class RoleListSerializer(serializers.ModelSerializer):
    company_uid = serializers.CharField(write_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    display_name = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = CompanyRole
        fields = [
            "uid",
            "name",
            "display_name",
            "kind",
            "is_system",
            "description",
            "status",
            "company",
            "company_uid",
            "company_name",
            "permissions",
            "users",
        ]
        extra_kwargs = {"company": {"read_only": True}}

    def get_display_name(self, obj):
        return _role_display_name(obj)

    def get_users(self, obj):
        return UserSerializer([cu.user for cu in obj.assigned_users], many=True).data

    def get_permissions(self, obj):
        # Use the prefetched list (set via to_attr="permissions_list" in the view)
        # to avoid an N+1 query per role. Falls back to a live query if the
        # prefetch is absent (e.g. when this serializer is used elsewhere).
        permissions = getattr(obj, "permissions_list", None)
        if permissions is None:
            permissions = obj.permission.select_related("content_type").all()
        permission_dict = {}
        for permission in permissions:
            app_label = permission.content_type.app_label
            model_name = permission.content_type.model
            app_dict = permission_dict.setdefault(app_label, {"model": {}})
            model_dict = app_dict["model"].setdefault(model_name, [])
            model_dict.append(
                {"id": permission.id, "codename": permission.codename}
            )
        return {"app_label": permission_dict}


class RoleSlimSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = CompanyRole
        fields = ["uid", "name", "display_name", "kind"]

    def get_display_name(self, obj):
        return _role_display_name(obj)


class RoleModifySerializer(serializers.ModelSerializer):
    permissions = serializers.ListField(
        child=serializers.IntegerField(), write_only=True
    )

    class Meta:
        model = CompanyRole
        fields = ["uid", "name", "description", "status", "permissions"]
        extra_kwargs = {"company": {"read_only": True}}

    def validate(self, attrs):
        if self.instance and self.instance.is_system:
            protected = {"name"}
            forbidden = {
                field
                for field in protected & set(attrs.keys())
                if attrs[field] != getattr(self.instance, field)
            }
            if forbidden:
                actor = (
                    getattr(self.context["request"].user, "email", None)
                    if "request" in self.context
                    else None
                )
                logger.warning(
                    "RoleModifySerializer.validate rejected system role edit "
                    "role_uid=%s name=%s forbidden_fields=%s by=%s",
                    self.instance.uid,
                    self.instance.name,
                    sorted(forbidden),
                    actor,
                )
                raise serializers.ValidationError(
                    f"System roles cannot have these fields changed: {', '.join(sorted(forbidden))}."
                )
        return attrs

    def update(self, instance, validated_data):
        permissions = validated_data.pop("permissions", None)
        before_perm_ids = set(instance.permission.values_list("id", flat=True))

        if permissions is not None:
            instance.permission.set(Permission.objects.filter(id__in=permissions))

        result = super().update(instance, validated_data)

        after_perm_ids = set(instance.permission.values_list("id", flat=True))
        actor = self.context["request"].user if "request" in self.context else None
        crud_log(
            logger,
            CrudAction.UPDATED,
            instance,
            actor=actor,
            extra={
                "added_perms": len(after_perm_ids - before_perm_ids),
                "removed_perms": len(before_perm_ids - after_perm_ids),
                "is_system": instance.is_system,
            },
        )
        return result
