from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from messageio.choices import InboxKindChoices, InboxStatusChoices
from messageio.models import Inbox, Thread

from common.django_rest.permissions.company_subscription import HaveSubscription

from ..serializers.support_and_tickets import (
    PrivateWeSupportTicketListSerializer,
    PrivateWeSupportTicketDetailsSerializer,
    PrivateWeSupportTicketThreadListSerializer,
)


class PrivateWeSupportTicketList(ListCreateAPIView):
    serializer_class = PrivateWeSupportTicketListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_support_ticket"

    def get_queryset(self):
        user = self.request.user
        filters = {"kind": InboxKindChoices.SUPPORT_AND_TICKET}
        if not user.is_superuser:
            filters["user"] = user
        return Inbox.objects.filter(**filters)


class PrivateWeSupportTicketDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeSupportTicketDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_support_ticket"

    def get_object(self):
        user = self.request.user
        filters = {
            "kind": InboxKindChoices.SUPPORT_AND_TICKET,
            "uid": self.kwargs.get("uid", None),
        }
        # Support staff reach every ticket; everyone else reaches their own.
        # This used to resolve the ticket on `uid` alone and only afterwards
        # assign `filters["user"] = user` -- into a dict nothing read again, so
        # the ownership check was written but never applied and any signed-in
        # user could open any ticket by uid. `Inbox` has no company column, so
        # the owning user is the tenant boundary here.
        if not user.is_superuser:
            filters["user"] = user

        instance = get_object_or_404(Inbox.objects.filter(**filters))
        if user.is_superuser:
            instance.target = user
            if instance.status == InboxStatusChoices.PENDING:
                instance.status = InboxStatusChoices.ON_GOING
            instance.save_dirty_fields()
            filters["target"] = user

        last_thread = instance.get_last_thread()
        if last_thread and user != last_thread.author:
            instance.is_seen = True
            instance.save_dirty_fields()
        return instance


class PrivateWeSupportTicketThreadList(ListCreateAPIView):
    serializer_class = PrivateWeSupportTicketThreadListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_support_ticket"

    def get_queryset(self):
        return Thread.objects.filter(inbox__uid=self.kwargs.get("uid", None))
