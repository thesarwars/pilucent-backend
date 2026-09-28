from django.urls import path

from weapi.django_rest.views.pdf.f940 import DownloadForm940View

urlpatterns = [
    path(
        "",
        DownloadForm940View.as_view(),
        name="weapi.pdf.f940",
    ),
]
