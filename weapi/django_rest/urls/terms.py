from django.urls import path

from weapi.django_rest.views.terms import (
    PrivateWeTermList,
    PrivateWeTermDetails,
)

urlpatterns = [
    path(
        r"",
        PrivateWeTermList.as_view(),
        name="weapi.terms.list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeTermDetails.as_view(),
        name="weapi.terms.details",
    ),
]
