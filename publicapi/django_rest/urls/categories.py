from django.urls import path

from publicapi.django_rest.views.categories import (
    PublicCategoryList,
    PublicCategoryDetails,
)

urlpatterns = [
    path(
        r"/<slug:slug>",
        PublicCategoryDetails.as_view(),
        name="publicapi.category-details",
    ),
    path(r"", PublicCategoryList.as_view(), name="public-category-list"),
]
