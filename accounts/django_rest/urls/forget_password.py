from django.urls import path, include

from ..views.forget_password import ForgetPasswordSendLinkView, ForgetPasswordView

urlpatterns = [
    path(
        r"/<uuid:uid>/<str:token>",
        ForgetPasswordView.as_view(),
        name="accounts.forget-password",
    ),
    path(
        r"/sent-link",
        ForgetPasswordSendLinkView.as_view(),
        name="accounts.forget-password-sent-link",
    ),
]
