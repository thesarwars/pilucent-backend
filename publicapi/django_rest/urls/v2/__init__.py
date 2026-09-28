from django.urls import path, include

urlpatterns = [
    path(
        "/subscription-plans",
        include("publicapi.django_rest.urls.v2.subscription_plans"),
    ),
]
