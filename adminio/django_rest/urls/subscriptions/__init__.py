from django.urls import path, include

urlpatterns = [
    path(
        "",
        include("adminio.django_rest.urls.subscriptions.v1"),
    ),
]
