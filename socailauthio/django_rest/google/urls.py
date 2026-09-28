from django.urls import path

from .views import GoogleLoginApi, GoogleLoginRedirectApi

urlpatterns = [
    path(r"/auth/google/", GoogleLoginApi.as_view(), name="auth-with-google"),
    path(
        r"/auth/google/callback/",
        GoogleLoginRedirectApi.as_view(),
        name="auth-with-google-callback",
    ),
]
