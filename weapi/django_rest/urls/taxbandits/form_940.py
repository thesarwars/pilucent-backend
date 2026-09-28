from django.urls import path
from weapi.django_rest.views.taxbandits.form_940 import (
    GetForm940ListView,
    GetForm940DetailsView,
    CreateForm940View,
    CreateForm940TransmitView,
    GetForm940PdfView,
)

urlpatterns = [
    path(r"/list", GetForm940ListView.as_view(), name="form-940-list"),
    path(
        r"/details/<str:SubmissionId>/<str:RecordIds>",
        GetForm940DetailsView.as_view(),
        name="form-940-details",
    ),
    path(r"/create", CreateForm940View.as_view(), name="form-940-create"),
    path(r"/transmit", CreateForm940TransmitView.as_view(), name="form-940-transmit"),
    path(
        r"/get-pdf/<str:SubmissionId>/<str:RecordIds>",
        GetForm940PdfView.as_view(),
        name="form-940-get-pdf",
    ),
]
