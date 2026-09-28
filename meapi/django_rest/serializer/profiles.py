from versatileimagefield.serializers import VersatileImageFieldSerializer

from django_otp.plugins.otp_totp.models import TOTPDevice

from rest_framework import serializers
from rest_framework.serializers import ModelSerializer, ValidationError

from accounts.models import User

from common.django_rest.helpers.decorators import set_auditlog_actor

from companyio.django_rest.serializers.common import (
    PrivateWeCompanySlimSerializer,
    PrivateCompanyDesignationSlimSerializer,
    PrivateCompanyUserWithPermissionSlimSerializer,
)

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)


class PrivateMeProfileDetailSerializer(ModelSerializer):
    image = VersatileImageFieldSerializer(
        sizes=[
            ("original", "url"),
            ("at350x350", "crop__350x350"),
        ],
    )
    company = PrivateWeCompanySlimSerializer(
        read_only=True, source="get_active_company"
    )
    designation = PrivateCompanyDesignationSlimSerializer(
        read_only=True, source="get_designation"
    )
    permission = PrivateCompanyUserWithPermissionSlimSerializer(
        read_only=True, source="companyuser_set.first"
    )
    employee = PrivateCompanyEmployeeSlimSerializer(
        read_only=True, source="get_employee"
    )
    is_employee = serializers.SerializerMethodField()
    is_2fa_enabled = serializers.SerializerMethodField()
    # Onboarding completion vs. login access are distinct: `is_joined` reflects a
    # finished onboarding pipeline, while `is_access_enabled` tells the frontend
    # whether this account is allowed to authenticate.
    is_joined = serializers.SerializerMethodField()
    is_access_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "uid",
            "name",
            "phone",
            "email",
            "is_email_verified",
            "is_admin",
            "is_staff",
            "is_superuser",
            "image",
            "is_sms_verification_enabled",
            "is_email_verification_enabled",
            "is_2fa_enabled",
            "description",
            "address",
            "country",
            "company",
            "permission",
            "designation",
            "employee",
            "is_employee",
            "is_joined",
            "is_access_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "is_email_verified",
            "is_admin",
            "is_staff",
            "is_superuser",
            "is_2fa_enabled",
            "created_at",
            "updated_at",
        ]

    def get_is_employee(self, obj):
        return obj.employee_set.exists()

    def get_is_2fa_enabled(self, obj):
        return TOTPDevice.objects.filter(user=obj, confirmed=True).exists()

    def get_is_joined(self, obj):
        employee = obj.get_employee()
        return bool(employee.is_joined) if employee else False

    def get_is_access_enabled(self, obj):
        # Non-employee users are never gated, so treat them as enabled.
        employee = obj.get_employee()
        return bool(employee.is_access_enabled) if employee else True


class PrivateMeProfileChangePasswordSrializer(ModelSerializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["old_password", "new_password"]

    @set_auditlog_actor
    def update(self, instance, validated_data):

        old_password = validated_data["old_password"]
        new_password = validated_data["new_password"]
        if not instance.check_password(old_password):
            raise ValidationError({"details": "Old password doesn't match"})
        instance.set_password(new_password)
        return super().update(instance, validated_data)
