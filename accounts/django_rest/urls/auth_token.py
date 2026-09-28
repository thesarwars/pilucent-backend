from django.urls import path

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from accounts.django_rest.serializers.auth_token import (
    AccessGatedTokenObtainPairSerializer,
)


class AccessGatedTokenObtainPairView(TokenObtainPairView):
    serializer_class = AccessGatedTokenObtainPairSerializer


urlpatterns = [
    # JWT
    path(r"", AccessGatedTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path(r"/refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path(r"/verify", TokenVerifyView.as_view(), name="token_verify"),
]
