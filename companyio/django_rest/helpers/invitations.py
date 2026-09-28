"""Shared logic for creating and accepting company invitations."""

import logging
import os

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.django_rest.helpers.crud_logger import CrudAction, crud_log
from common.django_rest.helpers.tasks import send_email

from companyio.choices import CompanyInvitationStatusChoices
from companyio.models import CompanyInvitation, CompanyUser

from .invitation_code import generate_unique_invitation_code

logger = logging.getLogger(__name__)

# How long an invitation stays valid (matches the legacy signed-token window).
INVITATION_TTL = timedelta(hours=48)


def create_invitation(*, company, email, roles, invited_by):
    """Create (or refresh) a pending invitation for ``email`` into ``company``.

    If a pending invitation already exists for this company+email we reuse it
    (refreshing roles and expiry) rather than violating the uniqueness
    constraint -- this makes "invite again" idempotent.
    """
    invitation = CompanyInvitation.objects.filter(
        company=company,
        email=email,
        status=CompanyInvitationStatusChoices.PENDING,
    ).first()

    if invitation is None:
        invitation = CompanyInvitation.objects.create(
            company=company,
            email=email,
            invited_by=invited_by,
            code=generate_unique_invitation_code(CompanyInvitation),
            expires_at=timezone.now() + INVITATION_TTL,
        )
    else:
        invitation.invited_by = invited_by
        invitation.expires_at = timezone.now() + INVITATION_TTL
        invitation.save(update_fields=["invited_by", "expires_at", "updated_at"])

    if roles is not None:
        invitation.roles.set(roles)
    return invitation


def send_invitation_email(invitation, *, link_token=None):
    """Email the invitee a join link (token-based) and the manual code."""
    frontend_url = os.environ.get("BASE_FRONTEND_URL", "http://localhost:3000")
    if link_token:
        join_link = f"{frontend_url}/auth/verify-invitation/{link_token}"
    else:
        join_link = f"{frontend_url}/auth/join?code={invitation.code}"

    send_email(
        {
            "invitation_link": join_link,
            "invite_code": invitation.code,
            "user_name": invitation.email,
            "company": invitation.company,
        },
        "emails/onboard/user_invitation.html",
        invitation.email,
        "Invitation to join Balanzify",
    )


class InvitationError(Exception):
    """Raised when an invitation cannot be accepted (expired/revoked/mismatch)."""


@transaction.atomic
def accept_invitation(invitation, user, *, actor=None):
    """Accept ``invitation`` for ``user``: add their CompanyUser + roles.

    Validates state and that the user's email matches the invite. Idempotent
    against an already-existing membership (roles are merged, not duplicated).
    Returns the CompanyUser.
    """
    if invitation.status != CompanyInvitationStatusChoices.PENDING:
        raise InvitationError("This invitation is no longer pending.")
    if invitation.is_expired():
        invitation.status = CompanyInvitationStatusChoices.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise InvitationError("This invitation has expired.")
    if user.email.lower() != invitation.email.lower():
        raise InvitationError("This invitation was issued for a different email.")

    company_user, _ = CompanyUser.objects.get_or_create(
        user=user, company=invitation.company
    )
    roles = list(invitation.roles.all())
    if roles:
        company_user.roles.add(*roles)

    invitation.status = CompanyInvitationStatusChoices.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.accepted_user = user
    invitation.save(update_fields=["status", "accepted_at", "accepted_user", "updated_at"])

    crud_log(
        logger,
        CrudAction.ASSIGNED,
        company_user,
        actor=actor or user,
        extra={
            "flow": "invitation_accept",
            "company": invitation.company.name,
            "roles": "[" + ",".join(r.name for r in roles) + "]",
        },
    )
    return company_user
