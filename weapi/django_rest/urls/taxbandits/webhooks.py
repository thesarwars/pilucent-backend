from django.urls import path
from weapi.django_rest.views.taxbandits.webhooks import (
    EfileStatusChangeWebhookView,
    EfileStateStatusChangeWebhookView,
    PdfCompleteWebhookView,
    W9StatusChangeWebhookView,
    TinMatchingWebhookView,
    BusinessCompleteWebhookView,
)

urlpatterns = [
    path(r"/efile-status-change/", EfileStatusChangeWebhookView.as_view(), name="tb-efile-status"),
    path(r"/efile-state-status-change", EfileStateStatusChangeWebhookView.as_view(), name="tb-efile-state-status"),
    path(r"/pdf-complete", PdfCompleteWebhookView.as_view(), name="tb-pdf-complete"),
    path(r"/w9-status-change", W9StatusChangeWebhookView.as_view(), name="tb-w9-status"),
    path(r"/tin-matching", TinMatchingWebhookView.as_view(), name="tb-tin-matching"),
    path(r"/business-complete", BusinessCompleteWebhookView.as_view(), name="tb-business-complete"),
]
