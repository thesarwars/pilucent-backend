from django.urls import path

from weapi.django_rest.views.products import (
    PrivateWeProductList,
    PrivateWeProductDetails,
    PrivateWeBundleCreate,
    PrivateWeBundleDetails,
    PrivateWeBundleItemList,
    PrivateWeProductBulkCreate,
)

urlpatterns = [
    path(
        r"/bundles/<uuid:uid>/items",
        PrivateWeBundleItemList.as_view(),
        name="weapi.bundle-item-list",
    ),
    path(
        r"/bundles/<uuid:uid>",
        PrivateWeBundleDetails.as_view(),
        name="weapi.bundle-details",
    ),
    path(r"/bundles", PrivateWeBundleCreate.as_view(), name="weapi.bundle-create"),
    path(
        r"/<uuid:uid>",
        PrivateWeProductDetails.as_view(),
        name="weapi.product-details",
    ),
    path(r"", PrivateWeProductList.as_view(), name="weapi.product-list"),
    path(
        r"/bulk-create",
        PrivateWeProductBulkCreate.as_view(),
        name="weapi.product.bulk-create",
    ),
]
