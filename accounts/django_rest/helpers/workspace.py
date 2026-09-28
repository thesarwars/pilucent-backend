"""Helpers for the multi-company workspace switcher.

This module centralises two things:

  * minting a **company-scoped JWT** (an access/refresh pair that carries the
    selected company on the token, see ``tokens_for_company``), and
  * serialising a user's **memberships** into the payload the workspace picker
    renders (company card data + the "you own / you manage" summary).

The company claim rides on the *refresh* token; simplejwt's
``RefreshToken.access_token`` copies all non-reserved claims onto the derived
access token, and token rotation preserves them, so the selected company
survives refreshes without any extra wiring.
"""

from rest_framework_simplejwt.tokens import RefreshToken

from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME

# JWT claim names for the selected company. ``company_id`` is the DB primary key
# (used by the tenant middleware + RLS); ``company_uid`` is the public UUID.
COMPANY_ID_CLAIM = "company_id"
COMPANY_UID_CLAIM = "company_uid"


def tokens_for_company(user, company):
    """Return a company-scoped ``{"access", "refresh"}`` JWT pair for ``user``.

    The selected company is embedded as claims so every subsequent request is
    implicitly scoped to it (no header needed). ``company`` may be ``None`` to
    mint an *unscoped* pair (used right after login, before selection).
    """
    refresh = RefreshToken.for_user(user)
    if company is not None:
        refresh[COMPANY_ID_CLAIM] = company.id
        refresh[COMPANY_UID_CLAIM] = str(company.uid)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _company_user_is_owner(company_user):
    """True when the user holds this company's system 'admin' role.

    The creator of a company is granted the seeded system admin role, so we
    treat "has the admin role" as "owns this workspace" for the picker's
    owner/manager split and the Owner badge.
    """
    return any(
        role.name == ADMIN_GROUP_NAME and role.is_system
        for role in company_user.roles.all()
    )


def _primary_role_label(company_user, is_owner):
    """Pick the badge label shown on the company card.

    Owners always read as "Owner". Otherwise we surface the user's first role
    name (title-cased), falling back to "Viewer" when no role is assigned.
    """
    if is_owner:
        return "Owner"
    first_role = next(iter(company_user.roles.all()), None)
    if first_role is None:
        return "Viewer"
    return first_role.name.replace("_", " ").title()


def serialize_membership(company_user):
    """Serialise one CompanyUser into a workspace-picker company card."""
    company = company_user.company
    is_owner = _company_user_is_owner(company_user)
    logo = getattr(company, "logo", None)
    return {
        "company_uid": str(company.uid),
        "name": company.name,
        "legal_name": company.legal_name,
        "type": company.kind,
        "ein": company.business_id_no,
        "logo": logo.url if logo else None,
        "roles": [role.name for role in company_user.roles.all()],
        "role": _primary_role_label(company_user, is_owner),
        "is_owner": is_owner,
        "is_pinned": company_user.is_pinned,
        "last_opened_at": company_user.last_opened_at,
        # Stable seed the frontend can hash into a per-company avatar gradient.
        "avatar_seed": str(company.uid),
    }


def get_membership_queryset(user):
    """CompanyUsers for ``user`` with everything the picker needs, pinned first.

    Removed companies are excluded. A superadmin "deleting" a tenant sets
    ``status=REMOVED`` rather than erasing the row (the ledger has to survive),
    so the status is the only thing that makes the deletion mean anything --
    without this filter the workspace picker would keep offering it.
    """
    from companyio.choices import CompanyStatusChoices

    return (
        user.companyuser_set.select_related("company")
        .exclude(company__status=CompanyStatusChoices.REMOVED)
        .prefetch_related("roles")
        .order_by("-is_pinned", "-last_opened_at", "company__name")
    )


def serialize_memberships(user):
    """Return ``{"memberships": [...], "summary": {...}}`` for the picker."""
    memberships = [serialize_membership(cu) for cu in get_membership_queryset(user)]
    owned = sum(1 for m in memberships if m["is_owner"])
    return {
        "memberships": memberships,
        "summary": {
            "total": len(memberships),
            "owned": owned,
            "managed": len(memberships) - owned,
        },
    }
