from django.urls import path

from ..views.user_onboards import (
    UserOnboardListView,
    VerifyInvitationView,
    UserOnboardCreateView,
    UserOnboardProfileUpdateView,
    UserOnBoardEditDetailsView,
    UserOnboardResendInviteView,
)

urlpatterns = [
    path(r"/list", UserOnboardListView.as_view(), name="accounts.user-onboard-list"),
    path(
        r"/create", UserOnboardCreateView.as_view(), name="accounts.user-onboard-create"
    ),
    path(
        r"/verify/<str:token>",
        VerifyInvitationView.as_view(),
        name="accounts.verify-invitation",
    ),
    path(
        r"/profile-update",
        UserOnboardProfileUpdateView.as_view(),
        name="accounts.user-onboard-profile-update",
    ),
    path(
        r"/<uuid:uid>/resend-invite",
        UserOnboardResendInviteView.as_view(),
        name="accounts.user-onboard-resend-invite",
    ),
    path(
        r"/<uuid:uid>",
        UserOnBoardEditDetailsView.as_view(),
        name="accounts.user-onboard-edit-details",
    ),
]
