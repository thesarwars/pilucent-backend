import logging

from django.contrib.auth.models import Group

from django.db import transaction

from rest_framework import serializers

from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME

from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from ...models import User

from rest_framework_simplejwt.tokens import RefreshToken


logger = logging.getLogger(__name__)


class UserRegisterSerializer(serializers.ModelSerializer):
    token = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "uid",
            "email",
            "name",
            "password",
            "phone",
            "ip_address",
            "is_terms_service",
            "created_at",
            "updated_at",
            "token",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]
        extra_kwargs = {"password": {"write_only": True}}

    def get_token(self, user):
        token = {}
        token["access_token"] = str(RefreshToken.for_user(user).access_token)
        token["refresh_token"] = str(RefreshToken.for_user(user))
        return token

    @transaction.atomic
    def create(self, validated_data):
        """Self-signup. The new user becomes admin of their own company.

        Notes:
        - We deliberately do NOT create an Employee row here. An admin is not
          automatically an employee; if they want to be, they create an Employee
          record explicitly later.
        - The CompanyUser + system 'admin' CompanyRole are wired up when the
          user creates their first company via PrivateWeCompanySerializer.
        """
        user = User.objects.create_user(**validated_data)
        user.set_password(validated_data["password"])
        group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        user.is_admin = True
        user.groups.add(group)
        user.save()
        crud_log(
            logger,
            CrudAction.CREATED,
            user,
            actor=user,
            extra={"flow": "self_signup", "group": ADMIN_GROUP_NAME},
        )
        return user
