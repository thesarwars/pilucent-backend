from django.urls import path

from ..views.notifications import (
    PrivateMeNotificationList,
    PrivateMeNotificationDetails,
    PrivateMeNotificationMarkAllRead,
)

urlpatterns = [
    # Ahead of the <uuid:uid> route for clarity; that converter would not
    # match this path anyway.
    path(
        r"/mark-all-read",
        PrivateMeNotificationMarkAllRead.as_view(),
        name="meapi.notification-mark-all-read",
    ),
    path(
        r"/<uuid:uid>",
        PrivateMeNotificationDetails.as_view(),
        name="meapi.notificatio-details",
    ),
    path(r"", PrivateMeNotificationList.as_view(), name="meapi.notificatio-list"),
]
