from django.urls import path

from accounts.django_rest.views.totp_auth import (
    TOTPConfirmSetupView,
    TOTPDisableView,
    TOTPSetupView,
    TOTPVerifyView,
)

urlpatterns = [
    path("/setup", TOTPSetupView.as_view(), name="totp_setup"), #api/v1/accounts/totp/setup
    path("/setup/confirm", TOTPConfirmSetupView.as_view(), name="totp_confirm_setup"), #api/v1/accounts/totp/setup/confirm
    # path("/verify", TOTPVerifyView.as_view(), name="totp_verify"), #api/v1/accounts/totp/verify
    path("/disable", TOTPDisableView.as_view(), name="totp_disable"), #api/v1/accounts/totp/disable
]
