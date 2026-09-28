from django.urls import path, include

urlpatterns = [
    path("", include("datamigrationio.django_rest.urls.migrations")),
]
