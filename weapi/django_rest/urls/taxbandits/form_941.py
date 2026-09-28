from django.urls import path
from weapi.django_rest.views.taxbandits.form_941 import (
    GetForm941ListView,
    GetForm941DetailsView,
    CreateForm941View,
    GetForm941ValidateView,
    CreateForm941TransmitView,
    GetForm941PDFView,
)

urlpatterns = [
    path(r"/list", GetForm941ListView.as_view(), name="form-941-list"),
    path(
        r"/details/<str:SubmissionId>",
        GetForm941DetailsView.as_view(),
        name="form-941-details",
    ),
    path(r"/create", CreateForm941View.as_view(), name="form-941-create"),
    path(
        r"/validate/<str:SubmissionId>/<str:RecordIds>",
        GetForm941ValidateView.as_view(),
        name="form-941-validate",
    ),
    path(r"/transmit", CreateForm941TransmitView.as_view(), name="form-941-transmit"),
    path(
        r"/get-pdf/<str:SubmissionId>/<str:RecordIds>",
        GetForm941PDFView.as_view(),
        name="form-941-get-pdf",
    ),
]
