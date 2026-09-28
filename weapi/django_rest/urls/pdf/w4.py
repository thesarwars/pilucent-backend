from django.urls import path
from weapi.django_rest.views.pdf.w4 import DownloadFormW4View, DebugPDFFieldsView

urlpatterns = [
    path(
        r"/",
        DownloadFormW4View.as_view(),
        name="weapi.pdf.w4",
    ),
    path(
        r"/debug-fields/",
        DebugPDFFieldsView.as_view(),
        name="weapi.pdf.w4.debug_fields",
    ),
]