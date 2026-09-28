from django.urls import path

from weapi.django_rest.views.moov_money.account_settings import (
    MoovAccountListView,
    MoovIndustriesListView,
    MoovAccountMeDetailView,
    MoovAccountDetailsView,
    MoovAccountCreateView,
    MoovAccountUpdateView,
    MoovAccountAccessTokenView,
    MoovAccountCreateRepresentativesView,
    MoovAccountUpdateRepresentativesView,
    MoovAccountCapabilitiesListView,
    MoovAccountCreateCapabilitiesView,
    MoovAccountRepresentativesDetailView,
    MoovAccountBankMeAccountListView,
)

urlpatterns = [
    path(r"/list", MoovAccountListView.as_view(), name="moov-account-list"),
    path(r"/industries", MoovIndustriesListView.as_view(), name="moov-industries-list"),
    path(
        r"/me-detail", MoovAccountMeDetailView.as_view(), name="moov-account-me-detail"
    ),
    path(r"/me-detail/bank-list", MoovAccountBankMeAccountListView.as_view(), name="moov-account-me-bank-list"),
    path(
        r"/details/<str:account_uid>",
        MoovAccountDetailsView.as_view(),
        name="moov-account-details",
    ),
    path(r"/create", MoovAccountCreateView.as_view(), name="moov-account-create"),
    path(
        r"/update/<str:account_uid>",
        MoovAccountUpdateView.as_view(),
        name="moov-account-update",
    ),
    path(
        r"/access-token/<str:account_uid>",
        MoovAccountAccessTokenView.as_view(),
        name="moov-account-access-token",
    ),
    path(
        r"/create/<str:account_uid>/representatives",
        MoovAccountCreateRepresentativesView.as_view(),
        name="moov-account-create-representatives",
    ),
    path(
        r"/update/<str:account_uid>/representatives/<str:representative_uid>",
        MoovAccountUpdateRepresentativesView.as_view(),
        name="moov-account-update-representatives",
    ),
    path(
        r"/representative/<str:representative_uid>",
        MoovAccountRepresentativesDetailView.as_view(),
        name="moov-account-representative-details",
    ),
    path(
        r"/create/<str:account_uid>/capabilities",
        MoovAccountCreateCapabilitiesView.as_view(),
        name="moov-account-create-capabilities",
    ),
    path(
        r"/details/<str:account_uid>/capabilities",
        MoovAccountCapabilitiesListView.as_view(),
        name="moov-account-capabilities-list",
    ),
]
