from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView, get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from notificationio.choices import NotificationStatusChoices
from notificationio.models import Notification

from ..serializer.notifications import (
    PrivateMeNotificationListSerializer,
    PrivateMeNotificationDetailsSerializer,
)


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateMeNotificationList(ListAPIView):
    serializer_class = PrivateMeNotificationListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return Notification.objects.filter(
            status=NotificationStatusChoices.PUBLISHED, user=self.request.user
        )


class PrivateMeNotificationDetails(RetrieveAPIView):
    serializer_class = PrivateMeNotificationDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        _object = get_object_or_404(
            Notification.objects.filter(
                uid=self.kwargs.get("uid"),
                status=NotificationStatusChoices.PUBLISHED,
                user=self.request.user,
            )
        )
        _object.is_read = True
        _object.save_dirty_fields()
        return _object


class PrivateMeNotificationMarkAllRead(APIView):
    """Mark every unread notification for the signed-in user as read.

    There was no bulk endpoint, so the bell menu's "Mark all as read" had
    nothing to call. Marking one works only because
    `PrivateMeNotificationDetails` flips `is_read` as a side effect of its GET,
    which is not something the bulk action can reuse without fetching each
    notification one at a time.

    A single UPDATE rather than a loop: a busy account can have hundreds
    unread, and each `save()` would be its own round trip.
    """

    permission_classes = [IsGroupPermission]
    required_permissions = ["change_notification"]

    def post(self, request, *args, **kwargs):
        updated = Notification.objects.filter(
            status=NotificationStatusChoices.PUBLISHED,
            user=request.user,
            is_read=False,
        ).update(is_read=True)
        return Response({"updated": updated}, status=status.HTTP_200_OK)
