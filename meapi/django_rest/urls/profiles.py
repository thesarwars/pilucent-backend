from django.urls import path, include

from ..views.profiles import PrivateMeProfileDetails, PrivateMeProfileChangePasswordView

urlpatterns = [
    path(r"", PrivateMeProfileDetails.as_view(), name="meapi.profile-deails"),
    path(
        r"/change-password",
        PrivateMeProfileChangePasswordView.as_view(),
        name="meapi.profile-change-password",
    ),
]
