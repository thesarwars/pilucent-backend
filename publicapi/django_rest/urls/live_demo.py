from django.urls import path

from publicapi.django_rest.views.live_demo import (
    PublicWeLiveDemoCreate,
    PublicWeLiveDemoDetails,
    PublicWeLiveDemoList,
)

urlpatterns = [
    path(r"", PublicWeLiveDemoCreate.as_view(), name="public-we-account-create"),
    path(r"/list", PublicWeLiveDemoList.as_view(), name="public-we-account-list"),
    path(
        r"/<uuid:uid>",
        PublicWeLiveDemoDetails.as_view(),
        name="public-we-account-details",
    ),
]
