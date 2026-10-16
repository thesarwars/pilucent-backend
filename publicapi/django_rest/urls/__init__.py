from django.urls import path, include

from . import idcards

urlpatterns = [
    path(
        "/subscription-plans", include("publicapi.django_rest.urls.subscription_plan")
    ),
    path("/live-demo", include("publicapi.django_rest.urls.live_demo")),
    path("/categories", include("publicapi.django_rest.urls.categories")),
    path("/idcards", include("publicapi.django_rest.urls.idcards")),
    path("/idcard-media", include((idcards.media, "idcard-media"))),
]
