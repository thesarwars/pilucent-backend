from django.urls import path, include

urlpatterns = [
    path(
        "/subscriptions",
        include("weapi.django_rest.urls.subscriptions.v2"),
    ),
]
