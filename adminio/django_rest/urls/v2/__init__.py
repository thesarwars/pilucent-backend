from django.urls import path, include

urlpatterns = [
    path(
        "/subscriptions",
        include("adminio.django_rest.urls.subscriptions.v2"),
    ),
]
