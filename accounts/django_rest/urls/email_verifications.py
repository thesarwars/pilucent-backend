from django.urls import path

from ..views.email_verifications import UserEmailVerificationSendOTPView, UserEmailVerificationView

urlpatterns = [
    # JWT
    path(
        r"/send-otp",
        UserEmailVerificationSendOTPView.as_view(),
        name="accounts.email-verification-send-otp",
    ),
    path(
        r"",
        UserEmailVerificationView.as_view(),
        name="accounts.email-verification",
    ),
]
