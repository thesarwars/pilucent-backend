from django.urls import path, include

from weapi.django_rest.views.transactions.bank_deposits import (
    PrivateWeBankDepositListCreateView,
)

urlpatterns = [
    # Bank deposit
    path(
        r"",
        PrivateWeBankDepositListCreateView.as_view(),
        name="weapi.bank-deposit-list",
    ),
]
