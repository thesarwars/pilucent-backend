from django.urls import path
from weapi.django_rest.views.receipt_ocr import ParseReceiptView

urlpatterns = [
    path(r"", ParseReceiptView.as_view(), name="parse-receipt"),
]
