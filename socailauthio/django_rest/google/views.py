import requests

from django.http import JsonResponse

from django.shortcuts import redirect

from rest_framework.views import APIView

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from django.core.files.base import ContentFile

from rest_framework.response import Response

from accounts.models import User
from accounts.django_rest.helpers.login_access import (
    ACCESS_DISABLED_MESSAGE,
    has_login_access,
)

from .mixins import PublicApiMixin, ApiErrorsMixin

from .serializers import GoogleUserSerializer, InputSerializer

from .utils import GoogleRawLoginFlowService


def generate_tokens_for_user(user):
    """
    Generate access and refresh tokens for the given user
    """
    serializer = TokenObtainPairSerializer()
    token_data = serializer.get_token(user)
    access_token = token_data.access_token
    refresh_token = token_data

    return access_token, refresh_token


class GoogleLoginRedirectApi(PublicApiMixin, APIView):
    def get(self, request, *args, **kwargs):
        google_login_flow = GoogleRawLoginFlowService()

        authorization_url, state = google_login_flow.get_authorization_url()

        request.session["google_oauth2_state"] = state
        request.session.save()
        return redirect(authorization_url)


class GoogleLoginApi(PublicApiMixin, ApiErrorsMixin, APIView):
    serializer_class = InputSerializer

    def get(self, request, *args, **kwargs):
        input_serializer = self.serializer_class(data=request.GET)

        if not input_serializer.is_valid():
            return JsonResponse({"error": "Invalid input parameters"}, status=400)

        validated_data = input_serializer.validated_data
        code = validated_data.get("code")
        error = validated_data.get("error")
        state = validated_data.get("state")

        if error:
            return JsonResponse({"error": error}, status=400)
        if not code or not state:
            return JsonResponse({"error": "Code and state are required."}, status=400)

        session_state = request.session.get("google_oauth2_state")
        if not session_state:
            return JsonResponse(
                {"error": "CSRF check failed: state not in session."}, status=400
            )

        del request.session["google_oauth2_state"]
        if state != session_state:
            return JsonResponse(
                {"error": "CSRF check failed: state mismatch."}, status=400
            )

        try:
            google_login_flow = GoogleRawLoginFlowService()
            google_tokens = google_login_flow.get_tokens(code=code)
            id_token_decoded = google_tokens.decode_id_token()
            user_info = google_login_flow.get_user_info(google_tokens=google_tokens)
            user_email = id_token_decoded["email"]
            try:
                user = User.objects.get(email=user_email)
                if not has_login_access(user):
                    return JsonResponse(
                        {"error": ACCESS_DISABLED_MESSAGE}, status=403
                    )
                access_token, refresh_token = generate_tokens_for_user(user)
                response_data = {
                    "user": GoogleUserSerializer(user).data,
                    "access": str(access_token),
                    "refresh": str(refresh_token),
                }
                return Response(response_data)
            except User.DoesNotExist:
                from django.contrib.auth.models import Group
                from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME

                username = user_email.split("@")[0]
                first_name = user_info.get("given_name", "")
                last_name = user_info.get("family_name", "")
                image_url = user_info.get("picture", "")
                name = f"{first_name} {last_name}"

                user = User.objects.create(
                    email=user_info["email"],
                    name=name,
                    is_email_verified=True,
                    is_admin=True,
                )
                # New Google users become admins of their own company (mirrors self-signup).
                # Their Company + CompanyUser + system 'admin' CompanyRole are wired up
                # when they create their first company via PrivateWeCompanySerializer.
                #
                # `is_staff` is deliberately NOT set. It is the Django-admin gate, and
                # this group carries `Permission.objects.all()` (group_seeds.py), so
                # setting it handed every Google signup the full admin site. Admin
                # requests never set the `app.company_id` GUC and `common/db/rls.py` is
                # permissive when it is unset, so row-level security did not contain
                # them either -- the combination was cross-tenant read/write.
                # `is_admin` stays: it means "admin of their own company", is resolved
                # against `get_active_company()`, and self-signup
                # (accounts/django_rest/serializers/user_register.py) has always set it.
                # Platform-level access is `is_superuser` (adminio/mixins.py:37), which
                # neither signup path grants.
                admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
                user.groups.add(admin_group)
                if image_url:
                    image_response = requests.get(image_url)
                    if image_response.status_code == 200:
                        image_content = ContentFile(image_response.content)
                        user.image.save(f"{username}_profile.jpg", image_content)

                access_token, refresh_token = generate_tokens_for_user(user)
                response_data = {
                    "user": GoogleUserSerializer(user).data,
                    "access": str(access_token),
                    "refresh": str(refresh_token),
                }
                return Response(response_data)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
