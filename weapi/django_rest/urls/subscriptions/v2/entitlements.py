from django.urls import path

from weapi.django_rest.views.subscriptions.v2.entitlements import (
    PrivateWeAccessManifest,
    PrivateWeEntitlementCheck,
)

urlpatterns = [
    path(
        r"/access-manifest",
        PrivateWeAccessManifest.as_view(),
        name="weapi.access-manifest",
    ),
    path(
        r"/check",
        PrivateWeEntitlementCheck.as_view(),
        name="weapi.entitlement-check",
    ),
]
