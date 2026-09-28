from django.urls import path
from weapi.django_rest.views.brands import (
    PrivateWeBrandList,
    PrivateWeBrandDetails,
)

urlpatterns = [
    path(r"", PrivateWeBrandList.as_view(), name="weapi.brand-list"),
    path(r"/<uuid:uid>", PrivateWeBrandDetails.as_view(), name="weapi.brand-details"),
]
