from django.urls import path
from weapi.django_rest.views.taxbandits.business import (
    GetBusinessListView,
    GetBusinessDetailView,
    CreateBusinessView,
    UpdateBusinessView,
    DeleteBusinessDetailView,
)

urlpatterns = [
    path(r"/list", GetBusinessListView.as_view(), name="business-list"),
    path(
        r"/detail",
        GetBusinessDetailView.as_view(),
        name="business-detail",
    ),
    path(r"/create", CreateBusinessView.as_view(), name="business-create"),
    path(r"/update", UpdateBusinessView.as_view(), name="business-update"),
    path(
        r"/delete",
        DeleteBusinessDetailView.as_view(),
        name="business-delete",
    ),
]
