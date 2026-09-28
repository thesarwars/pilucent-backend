"""Workspace-switcher endpoints: list memberships, select/switch, pin a company.

These power the standalone pre-app picker described in the Workspace Switcher
spec: after login the client lists the user's companies, the user opens one
("securing your session") which exchanges it for a company-scoped token, and
may pin/unpin companies.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.django_rest.helpers.workspace import serialize_memberships
from accounts.django_rest.serializers.workspace import (
    JoinByCodeSerializer,
    PinCompanySerializer,
    SelectCompanySerializer,
)


class WorkspaceMembershipsView(APIView):
    """GET the authenticated user's companies + owned/managed summary.

    Same payload the login response embeds; exposed standalone so the picker
    can refresh after creating/joining a company without re-authenticating.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(serialize_memberships(request.user))


class SelectCompanyView(APIView):
    """POST { company_uid } -> company-scoped { access, refresh, company }.

    Used both for the first selection from the picker and for switching company
    later (the frontend's 'switch-company' is the same exchange).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SelectCompanySerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)


class PinCompanyView(APIView):
    """POST { company_uid, is_pinned? } -> toggle/set pin, returns the company card."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PinCompanySerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        company = serializer.save()
        return Response({"company": company}, status=status.HTTP_200_OK)


class JoinByCodeView(APIView):
    """POST { code } -> join a company via invite code; returns scoped token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = JoinByCodeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
