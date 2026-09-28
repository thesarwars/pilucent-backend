import logging

from versatileimagefield.serializers import VersatileImageFieldSerializer

from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError

from companyio.models import Company, CompanyUser

from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from adminio.models import CompanyRole

from django.contrib.auth.models import Permission, Group


logger = logging.getLogger(__name__)


class PrivateWeCompanySerializer(ModelSerializer):
    legal_address = SerializerMethodField(read_only=True)

    logo = VersatileImageFieldSerializer(
        sizes=[
            ("original", "url"),
            ("at350x350", "crop__350x350"),
        ],
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Company
        fields = [
            "uid",
            "name",
            "legal_name",
            "kind",
            "status",
            "business_id_no",
            "vat_number",
            "time_zone",
            "email",
            "phone",
            "website",
            "company_addresses",
            "customer_facing_address",
            "legal_address",
            "logo",
            "created_at",
            "updated_at",
        ]
        # Must be inside Meta -- on the class body DRF ignores it and every
        # field stays writable. `status` is read-only here because it accepts
        # REMOVED, which deactivates the tenant; that belongs to the superadmin
        # console, not to a company-facing endpoint. See weapi/.../we.py.
        read_only_fields = [
            "uid",
            "status",
            "created_at",
            "updated_at",
            "legal_address",
        ]

    def get_legal_address(self, obj):
        return obj.get_legal_address()

    def validate_company_addresses(self, value):
        # Clients sometimes send this JSONField as a JSON-encoded *string*
        # (double-encoded) rather than an object. Normalise to a dict so the
        # stored value is always a mapping that downstream code can `.get()`.
        if isinstance(value, str):
            import json

            value = value.strip()
            if not value:
                return {}
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                raise ValidationError("Must be a valid JSON object.")
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise ValidationError("Must be a JSON object.")
        return value

    def validate(self, attrs):
        attrs.pop("legal_address", None)
        user = self.context["request"].user

        # Multi-company: a user may own several organizations. We no longer block
        # creating an additional company when the user already has a membership;
        # each create seeds its own system roles and an admin membership for the
        # creator (see ``create``).
        attrs["user"] = user
        return super().validate(attrs)

    @set_auditlog_actor
    def create(self, validated_data):
        user = validated_data.pop("user", None)

        # Creating company
        company = Company.objects.create(**validated_data)

        # Seed system roles for this company and assign the admin role to the creator.
        admin_role, _, _ = self.seed_company_roles(company)
        cu = CompanyUser.objects.create(company=company, user=user)
        cu.roles.add(admin_role)

        crud_log(
            logger,
            CrudAction.CREATED,
            company,
            actor=user,
            extra={"seeded_roles": "admin,user,employee"},
        )
        crud_log(
            logger,
            CrudAction.ASSIGNED,
            cu,
            actor=user,
            extra={"role": admin_role.name, "company": company.name},
        )
        return company

    def seed_company_roles(self, company):
        """Seed the three system CompanyRoles for a freshly-created company.

        Mirrors the permissions of the matching Django Group (admin/user/employee).
        Returns (admin_role, user_role, employee_role).
        """
        from accounts.django_rest.helpers.group_seeds import (
            ADMIN_GROUP_NAME,
            USER_GROUP_NAME,
            EMPLOYEE_GROUP_NAME,
        )
        from adminio.choices import CompanyRoleKindChoices

        specs = [
            (ADMIN_GROUP_NAME, CompanyRoleKindChoices.USER),
            (USER_GROUP_NAME, CompanyRoleKindChoices.USER),
            (EMPLOYEE_GROUP_NAME, CompanyRoleKindChoices.EMPLOYEE),
        ]
        created_roles = {}
        for group_name, kind in specs:
            role, _ = CompanyRole.objects.get_or_create(
                company=company,
                name=group_name,
                defaults={"kind": kind, "is_system": True},
            )

            # Backfill for older companies created before `is_system` was enforced.
            # We intentionally use a queryset update to bypass `CompanyRole.clean()`.
            if (not role.is_system) or (role.kind != kind):
                CompanyRole.objects.filter(pk=role.pk).update(is_system=True, kind=kind)
                role.is_system = True
                role.kind = kind

            group = Group.objects.filter(name=group_name).first()
            if group:
                role.permission.set(Permission.objects.filter(group=group))
            created_roles[group_name] = role
        return (
            created_roles[ADMIN_GROUP_NAME],
            created_roles[USER_GROUP_NAME],
            created_roles[EMPLOYEE_GROUP_NAME],
        )

    # Backward-compat shim for callers that imported the old name.
    def create_company_role(self, company):
        admin_role, _, _ = self.seed_company_roles(company)
        return admin_role