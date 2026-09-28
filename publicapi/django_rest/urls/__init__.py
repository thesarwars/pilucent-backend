from django.urls import path, include

urlpatterns = [
    path(
        "/subscription-plans", include("publicapi.django_rest.urls.subscription_plan")
    ),
    path("/live-demo", include("publicapi.django_rest.urls.live_demo")),
    path("/categories", include("publicapi.django_rest.urls.categories")),
]
