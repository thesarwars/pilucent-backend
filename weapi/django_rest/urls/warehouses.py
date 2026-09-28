from django.urls import path

from ..views.warehouses import (
    PrivateWeWarehouseListCreateView,
    PrivateWeWarehouseRetrieveUpdateView,
)

urlpatterns = [
    path(
        "",
        PrivateWeWarehouseListCreateView.as_view(),
        name="weapi.warehouse-list-create",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeWarehouseRetrieveUpdateView.as_view(),
        name="weapi.warehouse-details",
    ),
]
