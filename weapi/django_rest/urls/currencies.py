from django.urls import path

from ..views.currencies import PrivateWeCurrencyList, PrivateWeCurrencyDetails

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeCurrencyDetails.as_view(),
        name="weapi.currency-details",
    ),
    path(r"", PrivateWeCurrencyList.as_view(), name="weapi.currency-list"),
]
