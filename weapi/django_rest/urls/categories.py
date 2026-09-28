from django.urls import path

from weapi.django_rest.views.categories import (
    PrivateWeCategoryList,
    PrivateWeCategoryDetails,
)

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PrivateWeCategoryDetails.as_view(),
        name="weapi.category-details",
    ),
    path(r"", PrivateWeCategoryList.as_view(), name="weapi.category-list"),
]
