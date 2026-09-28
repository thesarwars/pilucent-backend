from django.urls import path
from weapi.django_rest.views.moov_money.transfer_money import (
    MoovTransferListView,
    MoovTransferDetailView,
    MoovTransferTimelineView,
    MoovTransferCancellationView,
    MoovTransferCancellationDetailView,
    MoovTransferCreateView,
    MeMoovTransferListView,
    MeMoovTransferDetailView,
)

urlpatterns = [
    path(r"/list", MoovTransferListView.as_view(), name="moov-transfer-list"),
    path(
        r"/detail/<str:transfer_uid>",
        MoovTransferDetailView.as_view(),
        name="moov-transfer-detail",
    ),
    path(
        r"/detail/<str:transfer_uid>/timeline",
        MoovTransferTimelineView.as_view(),
        name="moov-transfer-timeline",
    ),
    path(
        r"/cancellation/<str:transfer_uid>",
        MoovTransferCancellationView.as_view(),
        name="moov-transfer-cancellation",
    ),
    path(
        r"/cancellation/<str:transfer_uid>/<str:cancellation_uid>",
        MoovTransferCancellationDetailView.as_view(),
        name="moov-transfer-cancellation-detail",
    ),
    path(r"/create", MoovTransferCreateView.as_view(), name="moov-transfer-create"),
    path(r"/me-list", MeMoovTransferListView.as_view(), name="me-moov-transfer-list"),
    path(
        r"/me-details/<uuid:uid>",
        MeMoovTransferDetailView.as_view(),
        name="me-moov-transfer-detail",
    ),
]
