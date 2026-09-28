from django.urls import path
from weapi.django_rest.views.moov_money.bank_account_settings import (
    MoovBankAccountListView,
    MoovBankAccountCreateView,
    MoovBankAccountDetailsView,
    MoovBankAccountInitiateVerificationView,
    MoovBankAccountCompleteVerificationView,
    MoovBankAccountPaymentMethodList,
    MoovBankAccountPaymentsDetailsView,
    MoovBankAccountDeleteView,
)

urlpatterns = [
    path(r"/list", MoovBankAccountListView.as_view(), name="moov-bank-account-list"),
    path(
        r"/create", MoovBankAccountCreateView.as_view(), name="moov-bank-account-create"
    ),
    path(
        r"/details/<str:bank_account_uid>",
        MoovBankAccountDetailsView.as_view(),
        name="moov-bank-account-details",
    ),
    path(
        r"/initiate-verification/<str:bank_account_uid>",
        MoovBankAccountInitiateVerificationView.as_view(),
        name="moov-bank-account-initiate-verification",
    ),
    path(
        r"/complete-verification/<str:bank_account_uid>",
        MoovBankAccountCompleteVerificationView.as_view(),
        name="moov-bank-account-complete-verification",
    ),
    path(
        r"/delete/<str:bank_account_uid>",
        MoovBankAccountDeleteView.as_view(),
        name="moov-bank-account-delete",
    ),
    # payment method
    path(
        r"/payment-methods",
        MoovBankAccountPaymentMethodList.as_view(),
        name="moov-bank-account-payment-method-list",
    ),
    path(
        r"/payment-details/<str:bank_account_uid>",
        MoovBankAccountPaymentsDetailsView.as_view(),
        name="moov-bank-account-payments-details",
    ),
]
