from rest_framework import serializers

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.django_rest.helpers.login_access import (
    ACCESS_DISABLED_MESSAGE,
    has_login_access,
)
from accounts.django_rest.helpers.workspace import serialize_memberships


class AccessGatedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT login serializer for the multi-company workspace switcher.

    On top of issuing the JWT pair it:
      * blocks employee-linked users whose login access has not been enabled
        (e.g. a MANUAL_ENTRY employee an admin hasn't invited yet, or one whose
        access was revoked), and
      * returns the user's company ``memberships`` plus an owned/managed
        ``summary`` so the client can render the company picker immediately.

    The token issued here is intentionally *unscoped* (no company claim): the
    client picks a company and exchanges it for a company-scoped token via the
    ``select-company`` endpoint.
    """

    def validate(self, attrs):
        data = super().validate(attrs)
        if not has_login_access(self.user):
            raise serializers.ValidationError({"detail": ACCESS_DISABLED_MESSAGE})
        data.update(serialize_memberships(self.user))
        return data
