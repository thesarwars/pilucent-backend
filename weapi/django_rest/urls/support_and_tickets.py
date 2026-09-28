from django.urls import path
from ..views.support_and_tickets import (
    PrivateWeSupportTicketList,
    PrivateWeSupportTicketDetails,
    PrivateWeSupportTicketThreadList,
)

urlpatterns = [
    path(
        r"/<uuid:uid>/threads",
        PrivateWeSupportTicketThreadList.as_view(),
        name="weapi.support-ticket-thread-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeSupportTicketDetails.as_view(),
        name="weapi.support-ticket-details",
    ),
    path(r"", PrivateWeSupportTicketList.as_view(), name="weapi.support-ticket-list"),
]
