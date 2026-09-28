import base64

from django.contrib.auth import authenticate

from django_otp.plugins.otp_totp.models import TOTPDevice

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.tokens import RefreshToken

from accounts.django_rest.helpers.login_access import (
    ACCESS_DISABLED_MESSAGE,
    has_login_access,
)


class TOTPSetupView(APIView):
    """Step 1: Generate a TOTP device and return the QR code URI + secret."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if device:
            return Response(
                {"error": "2FA is already activated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        TOTPDevice.objects.filter(user=user, confirmed=False).delete()

        device = TOTPDevice.objects.create(user=user, name="default", confirmed=False)

        secret_base32 = base64.b32encode(device.bin_key).decode("utf-8")

        return Response(
            {
                "otpauth_url": device.config_url,
                "secret_key": secret_base32,
            }
        )


class TOTPConfirmSetupView(APIView):
    """Step 2: User enters a code from their authenticator to prove they scanned the QR."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
        if not device:
            return Response(
                {"error": "No pending 2FA setup found. Call the setup endpoint first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            return Response({"message": "2FA activated successfully."})

        return Response(
            {"error": "Invalid code. Please try again."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class TOTPDisableView(APIView):
    """Disable 2FA by removing all TOTP devices for the user."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Current 2FA code is required to disable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if not device:
            return Response(
                {"error": "2FA is not enabled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not device.verify_token(token):
            return Response(
                {"error": "Invalid code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        TOTPDevice.objects.filter(user=user).delete()
        return Response({"message": "2FA has been disabled."})


class TOTPVerifyView(APIView):
    """Login verification: email + password + TOTP code → JWT tokens."""

    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")
        token = request.data.get("token")

        if not all([email, password, token]):
            return Response(
                {"error": "email, password, and token are all required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, email=email, password=password)
        if user is None:
            return Response(
                {"error": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not has_login_access(user):
            return Response(
                {"error": ACCESS_DISABLED_MESSAGE},
                status=status.HTTP_403_FORBIDDEN,
            )

        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if not device:
            return Response(
                {"error": "2FA is not enabled for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not device.verify_token(token):
            return Response(
                {"error": "Invalid 2FA code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "message": "Authenticated successfully.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )
