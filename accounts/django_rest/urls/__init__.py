from django.urls import path, include

urlpatterns = [
    # JWT
    path("/auth/token", include("accounts.django_rest.urls.auth_token")),
    path("/register", include("accounts.django_rest.urls.user_register")),
    path(
        "/email-verifications",
        include("accounts.django_rest.urls.email_verifications"),
    ),
    path("/forget-password", include("accounts.django_rest.urls.forget_password")),
    path("/employee-onboards", include("accounts.django_rest.urls.onboards")),
    path("/user-onboards", include("accounts.django_rest.urls.user_onboards")),
    path("/totp", include("accounts.django_rest.urls.totp_auth")),
    path("/workspace", include("accounts.django_rest.urls.workspace")),
]
