from versatileimagefield.serializers import VersatileImageFieldSerializer
from rest_framework import serializers
from rest_framework.serializers import ModelSerializer
from django.contrib.auth.models import Permission

from accounts.django_rest.helpers.group_seeds import SYSTEM_ROLE_DISPLAY_LABELS

from companyio.models import (
    Company,
    CompanyDepartment,
    CompanyDesignation,
    CompanySection,
    CompanyShift,
    CompanyUser,
)


class CompanyBaseSerializer(ModelSerializer):
    logo = VersatileImageFieldSerializer(
        sizes=[
            ("original", "url"),
            ("at350x350", "crop__350x350"),
        ],
    )

    class Meta:
        model = Company
        fields = ["name", "title", "logo", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateWeCompanySlimSerializer(CompanyBaseSerializer):

    class Meta:
        model = CompanyBaseSerializer.Meta.model
        fields = ["uid"] + CompanyBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCompanySlimSerializer(CompanyBaseSerializer):

    class Meta:
        model = CompanyBaseSerializer.Meta.model
        fields = ["slug"] + CompanyBaseSerializer.Meta.fields
        read_only_fields = fields


class CompanyDepartmentBaseSerializer(ModelSerializer):

    class Meta:
        model = CompanyDepartment
        fields = ["title", "code", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateCompanyDepartmentSlimSerializer(CompanyDepartmentBaseSerializer):

    class Meta:
        model = CompanyDepartmentBaseSerializer.Meta.model
        fields = ["uid"] + CompanyDepartmentBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCompanyDepartmentSlimSerializer(CompanyDepartmentBaseSerializer):

    class Meta:
        model = CompanyDepartmentBaseSerializer.Meta.model
        fields = ["slug"] + CompanyDepartmentBaseSerializer.Meta.fields
        read_only_fields = fields


class CompanyDesignationBaseSerializer(ModelSerializer):

    class Meta:
        model = CompanyDesignation
        fields = ["title", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateCompanyDesignationSlimSerializer(CompanyDesignationBaseSerializer):

    class Meta:
        model = CompanyDesignationBaseSerializer.Meta.model
        fields = ["uid"] + CompanyDesignationBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCompanyDesignationSerializer(CompanyDesignationBaseSerializer):

    class Meta:
        model = CompanyDepartmentBaseSerializer.Meta.model
        fields = ["slug"] + CompanyDepartmentBaseSerializer.Meta.fields
        read_only_fields = fields


class CompanyShiftBaseSerializer(ModelSerializer):

    class Meta:
        model = CompanyShift
        fields = [
            "title",
            "in_time",
            "out_time",
            "regular_hour",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateCompanyShiftSlimSerializer(CompanyShiftBaseSerializer):

    class Meta:
        model = CompanyShiftBaseSerializer.Meta.model
        fields = ["uid"] + CompanyShiftBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCompanyShiftSerializer(CompanyShiftBaseSerializer):

    class Meta:
        model = CompanyShiftBaseSerializer.Meta.model
        fields = ["slug"] + CompanyShiftBaseSerializer.Meta.fields
        read_only_fields = fields


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "name", "codename"]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation[instance.codename] = True
        return representation


class CompanyUserBaseSerializer(ModelSerializer):
    roles = serializers.SerializerMethodField()
    company = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = CompanyUser
        fields = ["roles", "company"]
        read_only_fields = fields

    def get_roles(self, obj):
        return [
            {
                "uid": str(r.uid),
                "name": r.name,
                # System roles ship with a friendlier display label (e.g. the
                # `employee` role surfaces as "Employee Self-Service"). Custom
                # roles fall back to their stored name.
                "display_name": SYSTEM_ROLE_DISPLAY_LABELS.get(r.name, r.name)
                if r.is_system
                else r.name,
                "kind": r.kind,
                "is_system": r.is_system,
            }
            for r in obj.roles.all()
        ]


class PrivateCompanyUserSlimSerializer(CompanyUserBaseSerializer):
    class Meta:
        model = CompanyUserBaseSerializer.Meta.model
        fields = ["uid"] + CompanyUserBaseSerializer.Meta.fields
        read_only_fields = fields


class PrivateCompanyUserWithPermissionSlimSerializer(CompanyUserBaseSerializer):
    # permissions = PermissionSerializer(source="permission", many=True, read_only=True)
    ext_permissions = serializers.SerializerMethodField()
    role_permissions = serializers.SerializerMethodField()

    class Meta:
        model = CompanyUserBaseSerializer.Meta.model
        fields = [
            "uid",
            "ext_permissions",
            "role_permissions",
        ] + CompanyUserBaseSerializer.Meta.fields
        read_only_fields = fields

    def get_ext_permissions(self, obj):
        permission_dict = {}
        for permission in obj.permission.all():
            app_label = permission.content_type.app_label
            model_name = permission.content_type.model
            
            if app_label not in permission_dict:
                permission_dict[app_label] = {"model" : {}}
                
            if model_name not in  permission_dict[app_label]["model"]:
                permission_dict[app_label]["model"][model_name] = []
                
            permission_dict[app_label]["model"][model_name].append({
                    "id" :permission.id,
                    "codename" : permission.codename,
                })
        return {"app_label" : permission_dict}
    
    def get_role_permissions(self, obj):
        permission_dict = {}
        if obj.user.is_superuser:
            return {"app_label": {"all_permissions": True}}

        seen = set()
        for role in obj.roles.all():
            for permission in role.permission.all():
                if permission.id in seen:
                    continue
                seen.add(permission.id)
                app_label = permission.content_type.app_label
                model_name = permission.content_type.model
                if app_label not in permission_dict:
                    permission_dict[app_label] = {"model": {}}
                if model_name not in permission_dict[app_label]["model"]:
                    permission_dict[app_label]["model"][model_name] = []
                permission_dict[app_label]["model"][model_name].append(
                    {"id": permission.id, "codename": permission.codename}
                )
        return {"app_label": permission_dict}