from django.urls import path

from weapi.django_rest.views.addresses import PrivateWeAddressList, PrivateWeAddressDetails


urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeAddressDetails.as_view(),
        name="weapi.address-details",
    ),
    path(
        r"",
        PrivateWeAddressList.as_view(),
        name="weapi.address-list",
    )
]
