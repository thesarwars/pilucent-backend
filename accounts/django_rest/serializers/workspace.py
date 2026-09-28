"""Serializers for the workspace switcher: select / switch / pin a company."""

from django.utils import timezone

from rest_framework import serializers

from accounts.django_rest.helpers.login_access import ACCESS_DISABLED_MESSAGE
from accounts.django_rest.helpers.workspace import (
    serialize_membership,
    serialize_memberships,
    tokens_for_company,
)

from companyio.choices import CompanyInvitationStatusChoices, CompanyStatusChoices
from companyio.models import CompanyInvitation, CompanyUser
from companyio.django_rest.helpers.invitations import (
    InvitationError,
    accept_invitation,
)


class SelectCompanySerializer(serializers.Serializer):
    """Exchange a chosen company for a company-scoped JWT pair.

    Input is the company's public ``company_uid``. We verify the requesting
    user actually has a membership for it (and, if they are a gated employee of
    that company, that their access is enabled), stamp ``last_opened_at`` for
    the "last opened" ordering, and return a fresh scoped access/refresh pair.
    """

    company_uid = serializers.UUIDField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        company_user = (
            CompanyUser.objects.select_related("company")
            .prefetch_related("roles")
            .filter(user=user, company__uid=attrs["company_uid"])
            .first()
        )
        if company_user is None:
            raise serializers.ValidationError(
                {"company_uid": "You do not have access to this company."}
            )

        # A removed company cannot be entered. Deletion is soft (the ledger has
        # to survive), so this check is what makes it take effect; reusing the
        # non-membership message keeps the two indistinguishable to a caller.
        if company_user.company.status == CompanyStatusChoices.REMOVED:
            raise serializers.ValidationError(
                {"company_uid": "You do not have access to this company."}
            )

        # Per-company login gate: an employee of this company whose access was
        # not enabled cannot enter this workspace (other workspaces still work).
        employee = user.employee_set.filter(company=company_user.company).first()
        if employee is not None and not employee.is_access_enabled:
            raise serializers.ValidationError({"detail": ACCESS_DISABLED_MESSAGE})

        attrs["company_user"] = company_user
        return attrs

    def create(self, validated_data):
        company_user = validated_data["company_user"]
        company_user.last_opened_at = timezone.now()
        company_user.save(update_fields=["last_opened_at", "updated_at"])

        tokens = tokens_for_company(company_user.user, company_user.company)
        return {
            **tokens,
            "company": serialize_membership(company_user),
        }


class PinCompanySerializer(serializers.Serializer):
    """Toggle (or explicitly set) the pinned state of one of the user's companies."""

    company_uid = serializers.UUIDField(write_only=True)
    is_pinned = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        user = self.context["request"].user
        company_user = (
            CompanyUser.objects.select_related("company")
            .prefetch_related("roles")
            .filter(user=user, company__uid=attrs["company_uid"])
            .first()
        )
        if company_user is None:
            raise serializers.ValidationError(
                {"company_uid": "You do not have access to this company."}
            )
        attrs["company_user"] = company_user
        return attrs

    def create(self, validated_data):
        company_user = validated_data["company_user"]
        desired = validated_data.get("is_pinned")
        company_user.is_pinned = (
            (not company_user.is_pinned) if desired is None else bool(desired)
        )
        company_user.save(update_fields=["is_pinned", "updated_at"])
        return serialize_membership(company_user)


class JoinByCodeSerializer(serializers.Serializer):
    """Join a company by typing the invite code from the 'Add a company' modal.

    The authenticated user redeems a pending invitation whose ``code`` they
    were given. We enforce that their email matches the invite, add their
    membership, and return refreshed memberships plus a company-scoped token so
    the client can drop them straight into the new workspace.
    """

    code = serializers.CharField(write_only=True)

    def validate(self, attrs):
        invitation = (
            CompanyInvitation.objects.select_related("company")
            .filter(
                code__iexact=attrs["code"].strip(),
                status=CompanyInvitationStatusChoices.PENDING,
            )
            .first()
        )
        if invitation is None:
            raise serializers.ValidationError(
                {"code": "Invalid or already-used invite code."}
            )
        attrs["invitation"] = invitation
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        invitation = validated_data["invitation"]
        try:
            company_user = accept_invitation(invitation, user, actor=user)
        except InvitationError as exc:
            raise serializers.ValidationError({"code": str(exc)})

        return {
            **serialize_memberships(user),
            **tokens_for_company(user, company_user.company),
            "company": serialize_membership(company_user),
        }
