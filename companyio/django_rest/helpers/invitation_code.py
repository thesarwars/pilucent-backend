"""Human-enterable invite codes for the workspace 'Join with code' flow.

Format: ``BLZ-XXXX-XXX`` using an unambiguous alphabet (no 0/O/1/I) so a code
read off an email is easy to type. Codes are unique per invitation.
"""

import secrets

# Crockford-ish alphabet minus easily-confused characters.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _segment(length):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def generate_invitation_code():
    """Return a fresh code like ``BLZ-4F2A-9KQ`` (not yet checked for uniqueness)."""
    return f"BLZ-{_segment(4)}-{_segment(3)}"


def generate_unique_invitation_code(model):
    """Return a code guaranteed unique against ``model`` (a CompanyInvitation)."""
    for _ in range(10):
        code = generate_invitation_code()
        if not model.objects.filter(code=code).exists():
            return code
    # Extremely unlikely; widen the entropy as a fallback.
    return f"BLZ-{_segment(4)}-{_segment(4)}-{_segment(4)}"
