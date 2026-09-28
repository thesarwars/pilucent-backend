from django.urls import path
from weapi.django_rest.views.stock import (
    PrivateWeStockLevel,
    PrivateWeStockLevelDetails,
    PrivateWeStockAdjustment,
    PrivateWeStockAdjustmentDetails,
    PrivateWeStockAdjustmentItemList,
)

urlpatterns = [
    path(r"/level", PrivateWeStockLevel.as_view(), name="private_we_stock_level"),
    path(
        r"/level/<uuid:uid>",
        PrivateWeStockLevelDetails.as_view(),
        name="private_we_stock_level_details",
    ),
    path(
        r"/adjustment",
        PrivateWeStockAdjustment.as_view(),
        name="private_we_stock_adjustment",
    ),
    path(
        r"/adjustment/<uuid:uid>",
        PrivateWeStockAdjustmentDetails.as_view(),
        name="private_we_stock_adjustment_details",
    ),
    path(
        r"/adjustment/<uuid:uid>/items",
        PrivateWeStockAdjustmentItemList.as_view(),
        name="private_we_stock_adjustment_approve",
    ),
]
