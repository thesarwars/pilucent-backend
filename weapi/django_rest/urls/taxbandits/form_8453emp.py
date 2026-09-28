from django.urls import path

from weapi.django_rest.views.taxbandits.form_8453emp import (
    Start8453EmpView,
    SignatureStatusView,
)

urlpatterns = [
    path(r"/request-payer", Start8453EmpView.as_view(), name="start_8453emp"),
    path(r"/signature-status", SignatureStatusView.as_view(), name="signature_status"),
]
