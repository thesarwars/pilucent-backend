from django.urls import path

from ..views.user_register import UserRegisterView

urlpatterns = [path(r"", UserRegisterView.as_view(), name="accounts.register")]
