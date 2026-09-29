import os
import random
import string, json
import logging

from django.db import transaction
from django.contrib.auth.models import Group, Permission
from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    Serializer,
)
from rest_framework import serializers

from accounts.models import User
from accounts.choices import UserStatusChoices
from accounts.django_rest.helpers.group_seeds import USER_GROUP_NAME

from adminio.choices import CompanyRoleKindChoices, CompanyRoleStatusChoices
from adminio.models import CompanyRole

from common.django_rest.helpers.tasks import send_email
from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from companyio.models import CompanyUser

from ..helpers.invitation_token import (
    generate_invitation_token,
    verify_invitation_token,
)


logger = logging.getLogger(__name__)

from companyio.django_rest.serializers.common import (
    PrivateCompanyUserSlimSerializer,
    PrivateCompanyUserWithPermissionSlimSerializer,
)

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)


class UserOnboardSerializer(ModelSerializer):
    role_uids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        write_only=True,
    )

    class Meta:
        model = User
        fields = [
            "email",
            "role_uids",
            "uid",
            "name",
            "status",
            "created_at",
        ]
        read_only_fields = ["uid", "status", "created_at"]

    def validate_role_uids(self, role_uids):
        company = self.context["request"].user.get_active_company()
        if company is None:
            raise serializers.ValidationError("No active company for this user.")

        unique_uids = list(dict.fromkeys(role_uids))
        found_count = CompanyRole.objects.filter(
            uid__in=unique_uids,
            company=company,
            kind=CompanyRoleKindChoices.USER,
            status=CompanyRoleStatusChoices.ACTIVE,
        ).count()
        if found_count != len(unique_uids):
            raise serializers.ValidationError(
                "One or more roles were not found, inactive, or not part of your company."
            )
        return unique_uids

    @transaction.atomic
    def create(self, validated_data):
        role_uids = validated_data.pop("role_uids")
        actor = self.context["request"].user
        company = actor.get_active_company()

        from common.django_rest.helpers.subscription_limits import (
            enforce_subscription_create_limit,
        )
        from subscriptionio.choices import LimitMetricChoices
        from companyio.django_rest.helpers.invitations import (
            create_invitation,
            send_invitation_email,
        )

        enforce_subscription_create_limit(company, LimitMetricChoices.USER)

        roles = list(
            CompanyRole.objects.filter(
                uid__in=role_uids,
                company=company,
                kind=CompanyRoleKindChoices.USER,
                status=CompanyRoleStatusChoices.ACTIVE,
            )
        )
        email = validated_data["email"]
        role_names = [r.name for r in roles]

        # Record a persistent, revocable invitation (also exposes a join code).
        invitation = create_invitation(
            company=company, email=email, roles=roles, invited_by=actor
        )
        # A link-token keyed on the email keeps the existing verify-invitation
        # acceptance endpoint working.
        link_token = generate_invitation_token(email)

        existing_user = User.objects.filter(email=email).first()

        if existing_user is not None:
            # The invitee already has an account (likely a member of another
            # company). Do NOT create a new user or add the membership yet --
            # they accept the invitation (via link or join code), which adds the
            # CompanyUser for them. This is the multi-company join path.
            send_invitation_email(invitation, link_token=link_token)
            crud_log(
                logger,
                CrudAction.INVITED,
                existing_user,
                actor=actor,
                extra={
                    "flow": "user_onboard_existing",
                    "company": company.name,
                    "roles": "[" + ",".join(role_names) + "]",
                    "invitation_code": invitation.code,
                },
            )
            return existing_user

        # Brand-new invitee: create the DRAFT login identity and the membership
        # up-front (so they show up as a pending user), then email the link.
        temp_password = "".join(
            random.choices(string.ascii_letters + string.digits, k=8)
        )
        user = User.objects.create_user(
            email=email,
            password=temp_password,
            name=validated_data["name"],
            status=UserStatusChoices.DRAFT,
            is_email_verified=False,
        )

        # Place invited co-workers in the system 'user' Django group.
        user_group, _ = Group.objects.get_or_create(name=USER_GROUP_NAME)
        user.groups.add(user_group)

        send_invitation_email(invitation, link_token=link_token)

        # company membership
        cu = CompanyUser.objects.create(user=user, company=company)
        cu.roles.add(*roles)

        crud_log(
            logger,
            CrudAction.INVITED,
            user,
            actor=actor,
            extra={
                "flow": "user_onboard",
                "company": company.name,
                "roles": "[" + ",".join(role_names) + "]",
                "invitation_code": invitation.code,
            },
        )
        crud_log(
            logger,
            CrudAction.ASSIGNED,
            cu,
            actor=actor,
            extra={"roles": "[" + ",".join(role_names) + "]", "company": company.name},
        )
        return user


class UserListSerializer(ModelSerializer):
    is_employee = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()
    company_user = PrivateCompanyUserSlimSerializer(
        read_only=True, source="companyuser_set.first"
    )

    class Meta:
        model = User
        fields = [
            "uid",
            "name",
            "email",
            "phone",
            "image",
            "status",
            "is_employee",
            "employee",
            "company_user",
            "is_email_verified",
            "created_at",
        ]

    def get_is_employee(self, obj):
        # The list view's queryset prefetches employee_set into `_employees_for_list`
        # to avoid N+1; fall back to the relation if a non-list code path uses this
        # serializer directly.
        cached = getattr(obj, "_employees_for_list", None)
        if cached is not None:
            return bool(cached)
        return obj.employee_set.exists()

    def get_employee(self, obj):
        emp = _employee_in_company(obj)
        if emp is None:
            return None
        return {
            "uid": str(emp.uid),
            "code": emp.code,
            "status": emp.status,
            "is_joined": emp.is_joined,
            "is_access_enabled": emp.is_access_enabled,
            "designation": emp.designation.title if emp.designation_id else None,
            "department": emp.department.title if emp.department_id else None,
        }


class VerifyInvitationSerializer(Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        token = attrs.get("token")
        is_valid, user_email, error_message = verify_invitation_token(token)

        if not is_valid:
            raise serializers.ValidationError(error_message)

        try:
            user = User.objects.get(email=user_email)
            attrs["user"] = user
            return attrs
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found")


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["name", "phone", "image", "password"]
        extra_kwargs = {"password": {"write_only": True}}

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if password:
            instance.set_password(password)
        return super().update(instance, validated_data)


class UserOnBoardDetailsSerializer(serializers.ModelSerializer):
    employee = serializers.SerializerMethodField()
    company_user = PrivateCompanyUserWithPermissionSlimSerializer(
        read_only=True, source="companyuser_set.first"
    )

    class Meta:
        model = User
        fields = [
            "uid",
            "name",
            "email",
            "phone",
            "image",
            "status",
            "employee",
            "company_user",
            "is_email_verified",
            "created_at",
        ]

    def get_employee(self, obj):
        emp = _employee_in_company(obj)
        if emp is None:
            return None
        return {
            "uid": str(emp.uid),
            "code": emp.code,
            "status": emp.status,
            "is_joined": emp.is_joined,
            "is_access_enabled": emp.is_access_enabled,
            "designation": emp.designation.title if emp.designation_id else None,
            "department": emp.department.title if emp.department_id else None,
        }


def _employee_in_company(user):
    """The user's employee record as the onboarding views show it.

    The views prefetch it scoped to the active company into
    `_employees_for_list`; an empty list there means "no employee in this
    company", not "not prefetched" -- falling back to the unscoped relation
    would show another company's record. Without the prefetch, get_employee()
    resolves the active company itself.
    """
    cached = getattr(user, "_employees_for_list", None)
    if cached is not None:
        return cached[0] if cached else None
    return user.get_employee()


class UserOnBoardEditDetailsSerializer(serializers.ModelSerializer):
    name = serializers.CharField(required=False)
    image = serializers.ImageField(required=False)
    role_uids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=False,
        write_only=True,
    )
    employee_code = serializers.CharField(required=False)
    employee = PrivateCompanyEmployeeSlimSerializer(
        read_only=True, source="get_employee"
    )
    company_user = PrivateCompanyUserSlimSerializer(
        read_only=True, source="companyuser_set.first"
    )
    permission = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "name",
            "image",
            "role_uids",
            "employee_code",
            "employee",
            "company_user",
            "permission",
        ]

    def validate_employee_code(self, value):
        """An employee code is the BD business key and is never reassigned
        (docs/employee-profile.md §2.1). An unchanged code is accepted; it is
        refused here, before update() saves the user or stores an image.

        Compared against the user's employee in the *editor's* active company
        -- the record this endpoint displays -- not whichever company
        `get_employee()` would fall back to for a user employed by several.
        """
        if self.instance is None:
            return value
        request = self.context.get("request")
        company = request.user.get_active_company() if request is not None else None
        if company is None:
            # No company to edit within: there is no employee record to compare.
            return value
        employee = self.instance.employee_set.filter(company=company).first()
        if employee is not None and employee.code != value:
            raise serializers.ValidationError("An employee code is never reassigned.")
        return value

    def validate_role_uids(self, role_uids):
        request = self.context.get("request")
        company = request.user.get_active_company() if request else None

        unique_uids = list(dict.fromkeys(role_uids))
        qs = CompanyRole.objects.filter(uid__in=unique_uids, status=CompanyRoleStatusChoices.ACTIVE)
        if company is not None:
            qs = qs.filter(company=company)

        if qs.count() != len(unique_uids):
            raise serializers.ValidationError(
                "One or more roles were not found, inactive, or not part of your company."
            )
        return unique_uids

    @transaction.atomic
    def update(self, instance, validated_data):

        # Update user fields
        if "name" in validated_data:
            instance.name = validated_data.get("name")
        if "image" in validated_data:
            instance.image = validated_data.get("image")
        instance.save()

        # Update user roles if provided (replaces existing roles)
        actor = self.context["request"].user if "request" in self.context else None
        role_uids = validated_data.get("role_uids")
        company_user = instance.companyuser_set.first()
        if role_uids and company_user:
            company = actor.get_active_company() if actor else None
            roles_qs = CompanyRole.objects.filter(
                uid__in=role_uids,
                status=CompanyRoleStatusChoices.ACTIVE,
            )
            if company is not None:
                roles_qs = roles_qs.filter(company=company)
            roles = list(roles_qs)

            before = list(company_user.roles.values_list("name", flat=True))
            company_user.roles.set(roles)
            crud_log(
                logger,
                CrudAction.ROLES_CHANGED,
                company_user,
                actor=actor,
                extra={
                    "user": instance.email,
                    "before": "[" + ",".join(before) + "]",
                    "after": "[" + ",".join(r.name for r in roles) + "]",
                },
            )

        permission_ids = validated_data.get("permission")
        if permission_ids and company_user:
            permission_ids = json.loads(permission_ids)
            before_count = company_user.permission.count()
            custom_permissions = Permission.objects.filter(id__in=permission_ids)
            company_user.permission.set(custom_permissions)
            crud_log(
                logger,
                CrudAction.PERMISSIONS_CHANGED,
                company_user,
                actor=actor,
                extra={
                    "user": instance.email,
                    "before_count": before_count,
                    "after_count": company_user.permission.count(),
                },
            )

        return instance
