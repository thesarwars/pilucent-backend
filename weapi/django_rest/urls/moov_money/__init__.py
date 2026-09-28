from django.urls import path, include

from weapi.django_rest.views.moov_money.account_settings import MoovAccessTokenView
from weapi.django_rest.views.moov_money.webhooks import MoovWebhookView

urlpatterns = [
    path(r"/access-token", MoovAccessTokenView.as_view(), name="moov-access-token"),
    path(
        r"/webhook", MoovWebhookView.as_view(), name="moov-webhook"
    ),  # https://balanzifyapi.jumatechs.xyz/api/v1/we/moov-money/webhook
    path(r"/account", include("weapi.django_rest.urls.moov_money.account_settings")),
    path(
        r"/bank-account",
        include("weapi.django_rest.urls.moov_money.bank_account_settings"),
    ),
    path(r"/transfer", include("weapi.django_rest.urls.moov_money.transfer_money")),
]
